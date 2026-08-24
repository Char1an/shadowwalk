# How I built a shade-aware router in Python

*A weekend prototype for Chennai, Delhi, and Ahmedabad. Free data. Free tools. $0 total cost.*

---

Google Maps has never optimised a walking route for thermal comfort. It optimises for distance, occasionally for elevation. Never for whether you'll be cooked alive on the way.

At 2 PM in Ahmedabad in May, a sunlit sidewalk sits 15–20 °C hotter than one under a building's shadow. In Chennai and Delhi the numbers are the same. Heat-related deaths in these cities rise every year, and the victims are almost always outdoor walkers — gig workers, the elderly, school kids, tourists who trusted the little blue line.

I wanted a walking router that would nudge me toward shade at the price of a small detour. There isn't one you can just open on your phone. So I built one over a weekend, and here's how.

## The idea in one paragraph

Download a city's walking network and building footprints from OpenStreetMap. Compute the sun's azimuth and elevation for the current time. For every building, cast its 2-D shadow on the ground: translate the footprint away from the sun by `height / tan(elevation)` metres, take the union of original and shifted, then the convex hull. For every street edge, sample points every 5 metres and count how many fall inside any shadow polygon — that's the edge's `shade_score`, a number in [0, 1]. Then run Dijkstra with edge weight `length × (1 − α × shade_score)`. `α = 0` gives the fastest path; `α = 1` gives the shadiest.

The whole pipeline is about 350 lines of Python.

## The results, up front

Three Indian scenes at their worst-hour walkable moments, `α = 0.9`:

| City                          | Time  | Distance         | Shortest shaded | ShadowWalk shaded | Sun exposure saved |
|-------------------------------|-------|------------------|-----------------|-----------------|--------------------|
| **Chennai** — T. Nagar        | 08:00 | 1.31 → 1.51 km   | 33 %            | **68 %**        | **4.9 min**        |
| **Delhi** — Connaught Place   | 09:00 | 1.63 → 1.87 km   | 8 %             | **46 %**        | **6.1 min**        |
| **Ahmedabad** — Ashram Road   | 17:00 | 1.08 → 1.17 km   | 11 %            | **35 %**        | **2.6 min**        |

Delhi is the most striking: 8 % of a fastest walk between two central spots is shaded at 9 AM in May. Rerouting for a 240 m detour cuts sun exposure by six minutes — six minutes that used to happen at 39 °C with an aching UV index.

## The unglamorous parts

Three things ate most of my time.

**Building heights are a lie.** OSM's `height` tag is populated for a small fraction of buildings outside Europe. Falling back to `building:levels × 3 m` catches a chunk more. Everything else needs a default. If you set the default too low (say 6 m), no shadow ever stretches across a street and your router is useless. Too high (30 m), and everything is always shaded and your router is useless *and* dishonest. I settled on a 4-tier fallback: `height` → `levels × 3` → per-`building` type (office 24 m, apartments 15 m, tower 40 m, shed 3 m) → 15 m. That last tier moved mean edge shade in Chennai from 0.03 to 0.14 with no other changes.

I also wired up Microsoft's Global ML Building Footprints — 1.5 billion buildings tiled by web-mercator quadkey — hoping to get real heights. Turns out MS has heights for parts of Africa and SE Asia but not India; the US uses a completely different MS dataset. So the plumbing is done and correct, but the payoff is regional.

**Overpass rate-limits.** OSM's Overpass API is free and generous, but it gets grumpy under load. Mid-demo I had it refuse three consecutive Phoenix requests, then Delhi, then Ahmedabad. Fix: a three-mirror fallback chain (main → kumi.systems → private.coffee) plus aggressive disk caching keyed by `(lat, lon, radius)`. Once a neighbourhood is cached, the app is instant forever.

**The 2 PM problem.** At 14:00 in May in Chennai, the sun is at 62° elevation. Shadows are `height / tan(62°) ≈ height / 1.9` metres long — a 15 m building casts an 8 m shadow, which won't cross a 12 m street. This is honest physics; the router correctly reports "no shade available" and picks the shortest path. The demo-worthy hours in low-latitude India are 7–9 AM and 4–6 PM, when the sun is lower and shadows are meaningful. Delhi and Ahmedabad are more forgiving because higher latitudes and denser mid-rise coverage.

## The bit I'm proudest of

The shadow-polygon layer isn't just an algorithm — it's *visible*. Toggle "Overlay shadow polygons" in the app and grey blobs appear over the map at the current hour. Drag the time slider and they rotate and shrink and stretch as the sun moves. You can see *why* the router picked what it picked. Compare that to Google Maps' inscrutable "recommended route" and it's a different kind of transparency.

The original algorithm I wrote was ray-cast: for every sample point, cast a ray toward the sun and check whether any building's centroid was in the way and tall enough. It ran in 15 seconds on a Chennai neighbourhood and had subtle bugs (buildings whose centre was off-axis but whose edge blocked the ray got missed). Replacing it with precomputed shadow polygons made it both **correct** (real 2-D shadow geometry) and **10× faster** (single `contains` query on an STRtree instead of a directional test per building). The shadow layer is also what the visualisation eats — one code path serves both routing and rendering.

## The stack, for the curious

- `osmnx` for OSM downloads and the NetworkX graph
- `pvlib` for sun position (the same library people use for solar-panel yield modelling)
- `shapely` for shadow-polygon geometry, `STRtree` for the point-in-polygon queries
- `folium` for the map, `streamlit` + `streamlit-folium` for the UI
- Open-Meteo for temperature/UV/radiation (free, no API key)
- 21 pytest cases, mostly on the shade geometry
- Deployed to Streamlit Community Cloud (1 GB RAM ceiling; the disk cache is per-neighbourhood rather than per-city so it fits)

## What's next

- **Real heights**: LiDAR is the answer where cities publish it (Los Angeles, Portland, most European capitals). India doesn't have a good open source, which is the honest bottleneck.
- **Trees with actual heights**: currently modelled as flat canopy polygons. Adding the ETH Global Canopy Height 10 m raster would let deciduous trees defoliate seasonally.
- **Weather-aware wet-bulb**: sun-exposure minutes are one axis; humidity is the other. Chennai in July at 88 % humidity is worse than Delhi in May at 12 %.
- **Route feedback**: "did this actually feel cooler?" — a one-tap thumbs-up would train a personalised α over time.

## Try it

Repo: `github.com/…` · Live demo: `shadowwalk.streamlit.app`

Open the app, pick Delhi at 9 AM, click Connaught Place, click Janpath. Watch the blue route swing north to hug the shadows of the colonial-era arcades. Then drag the time slider to noon and watch it collapse back onto the shortest path — because at noon, no shade exists to route around.

That's the whole point.
