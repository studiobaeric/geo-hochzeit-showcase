// Generates a fully-local MapLibre style for the offline basemap.
//
// The basemap "light" flavor from @protomaps/basemaps, wired to:
//   - a local PMTiles vector source (served by Flask at /static/data/basemap.pmtiles)
//   - local glyph fonts  (/static/fonts/{fontstack}/{range}.pbf)
//   - a local sprite     (/static/sprites/light)
//
// Run from the tools/ dir:  node build_style.mjs
import { layers, namedFlavor } from "@protomaps/basemaps";
import { writeFileSync } from "node:fs";

const style = {
  version: 8,
  glyphs: "/static/fonts/{fontstack}/{range}.pbf",
  sprite: "/static/sprites/light",
  sources: {
    protomaps: {
      type: "vector",
      url: "pmtiles:///static/data/basemap.pmtiles",
      attribution: '© <a href="https://openstreetmap.org">OpenStreetMap</a> contributors'
    }
  },
  layers: layers("protomaps", namedFlavor("light"), { lang: "de" })
};

writeFileSync("../static/data/basemap-style.json", JSON.stringify(style, null, 2));
console.log("wrote static/data/basemap-style.json with", style.layers.length, "layers");
