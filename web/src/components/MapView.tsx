import { useEffect, useRef, type MutableRefObject } from "react";
import OlMap from "ol/Map";
import View from "ol/View";
import ImageLayer from "ol/layer/Image";
import TileLayer from "ol/layer/Tile";
import VectorLayer from "ol/layer/Vector";
import LayerGroup from "ol/layer/Group";
import ImageWMS from "ol/source/ImageWMS";
import TileWMS from "ol/source/TileWMS";
import Collection from "ol/Collection";
import VectorSource from "ol/source/Vector";
import GeoJSON from "ol/format/GeoJSON";
import { Draw, Modify, Select, Snap } from "ol/interaction";
import { click } from "ol/events/condition";
import { ScaleLine, defaults as defaultControls } from "ol/control";
import { Circle, Fill, Stroke, Style } from "ol/style";
import { unByKey } from "ol/Observable";
import type { EventsKey } from "ol/events";
import type Feature from "ol/Feature";
import type { Geometry } from "ol/geom";
import { api } from "../api";
import type { Basemap, GeoJSONFeature, ProjectConfig, TreeNode } from "../types";
import { PNG8, basemapLayer, ensureBasemapProjections, tileGridFor } from "../tiles";

// --- Kafle rastrów
// Rastry projektu (skany, mozaiki) idą jako kafle WMS na stałej siatce: te same adresy
// przy każdym oglądaniu, więc serwer (nginx przed QGIS) i przeglądarka mogą je cache'ować.
// Wektory zostają jednym obrazem WMS bez cache — zmieniają się przy edycji.
// Podkłady (ortofoto, topo, OSM...) pochodzą z katalogu Sophii, nie z projektu.

/** Nazwa WMS -> format kafli dla warstw rastrowych i mozaik (pozostałe = wektory). */
function tileFormats(config: ProjectConfig): Map<string, string> {
  const out = new Map<string, string>();
  for (const l of Object.values(config.layers)) if (l.tile_format) out.set(l.wms_name, l.tile_format);
  const walk = (n: TreeNode) => {
    if (n.kind === "raster_group") out.set(n.name, PNG8);
    n.children.forEach(walk);
  };
  walk(config.tree);
  return out;
}

export type Tool = "identify" | "select" | "draw" | "modify";

interface Props {
  config: ProjectConfig;
  wmsLayers: string[];               // kolejność rysowania: od spodu do wierzchu
  editLayerId: string | null;
  tool: Tool;
  reloadToken: number;               // zmiana => przeładuj obiekty warstwy edycyjnej i WMS
  basemaps: Basemap[];               // katalog podkładów (kolejność = sort_order)
  baseId: number | null;             // wybrany podkład (null = brak)
  overlayIds: Set<number>;           // włączone nakładki (np. cieniowanie)
  onIdentify: (layerId: string, pk: string) => void;
  onSelect: (layerId: string, feature: GeoJSONFeature) => void;
  onDrawn: (layerId: string, geometry: GeoJSONFeature["geometry"]) => void;
  onGeometryModified: (layerId: string, pk: string, geometry: GeoJSONFeature["geometry"]) => void;
  mapRef: MutableRefObject<OlMap | null>;
}

const editStyle = new Style({
  stroke: new Stroke({ color: "#d9480f", width: 2 }),
  fill: new Fill({ color: "rgba(217,72,15,0.15)" }),
  image: new Circle({ radius: 6, fill: new Fill({ color: "#d9480f" }), stroke: new Stroke({ color: "#fff", width: 2 }) }),
});

const DRAW_TYPE = { Point: "Point", Line: "LineString", Polygon: "Polygon" } as const;

export function MapView(props: Props) {
  const { config, wmsLayers, editLayerId, tool, reloadToken, mapRef } = props;
  const divRef = useRef<HTMLDivElement>(null);
  const wmsRef = useRef<ImageWMS | null>(null);
  const wmsLayerRef = useRef<ImageLayer<ImageWMS> | null>(null);
  const rasterGroupRef = useRef<LayerGroup | null>(null);
  const basemapGroupRef = useRef<LayerGroup | null>(null);
  const basemapLayersRef = useRef(new Map<string, TileLayer>());
  const tileLayersRef = useRef(new Map<string, TileLayer<TileWMS>>());
  const editSourceRef = useRef(new VectorSource<Feature<Geometry>>());
  const cbRef = useRef(props);
  cbRef.current = props;
  const crs = config.crs;
  const format = new GeoJSON({ dataProjection: crs, featureProjection: crs });

  // --- mapa: tworzona raz na projekt
  useEffect(() => {
    const wms = new ImageWMS({
      url: "/ows",
      params: { PROJECT: config.slug, VERSION: "1.1.1", FORMAT: "image/png", TRANSPARENT: "true", LAYERS: "" },
      ratio: 1.2,
      serverType: "qgis",
    });
    wmsRef.current = wms;
    const wmsLayer = new ImageLayer({ source: wms, visible: false });
    wmsLayerRef.current = wmsLayer;
    const rasterGroup = new LayerGroup();
    rasterGroupRef.current = rasterGroup;
    const basemapGroup = new LayerGroup();
    basemapGroupRef.current = basemapGroup;
    tileLayersRef.current = new Map();
    basemapLayersRef.current = new Map();
    const tileGrid = tileGridFor(crs);
    const map = new OlMap({
      target: divRef.current!,
      controls: defaultControls().extend([new ScaleLine()]),
      layers: [
        basemapGroup,
        rasterGroup,
        wmsLayer,
        new VectorLayer({ source: editSourceRef.current, style: editStyle }),
      ],
      // Poziomy powiększenia = rozdzielczości siatki kafli: kafle wyświetlane 1:1, ostre.
      view: new View({
        projection: crs, center: [500000, 400000], zoom: 6,
        resolutions: tileGrid.getResolutions(), constrainResolution: true,
      }),
    });
    if (config.extent) map.getView().fit(config.extent, { padding: [20, 20, 20, 20] });
    mapRef.current = map;
    return () => { map.setTarget(undefined); mapRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.slug]);

  // --- podkłady: wybrany podkład + włączone nakładki, w kolejności katalogu
  const { basemaps, baseId, overlayIds } = props;
  useEffect(() => {
    const group = basemapGroupRef.current;
    if (!group) return;
    let cancelled = false;
    (async () => {
      const active = basemaps.filter((b) => (b.is_overlay ? overlayIds.has(b.id) : b.id === baseId));
      await ensureBasemapProjections(active);
      if (cancelled) return;
      const layers = active
        .sort((a, b) => Number(a.is_overlay) - Number(b.is_overlay))   // podkład pod nakładkami
        .map((b) => {
          const key = `${b.id}@${b.version}`;
          let layer = basemapLayersRef.current.get(key);
          if (!layer) {
            layer = basemapLayer(b, crs);
            basemapLayersRef.current.set(key, layer);
          }
          return layer;
        });
      group.setLayers(new Collection(layers));
    })().catch(console.error);
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [basemaps, baseId, overlayIds, config.slug]);

  // --- widoczne warstwy: rastry jako kafle (każdy osobno), wektory jednym obrazem WMS na wierzchu
  useEffect(() => {
    const wms = wmsRef.current;
    const group = rasterGroupRef.current;
    if (!wms || !group) return;
    const formats = tileFormats(config);
    const tileGrid = tileGridFor(crs);
    const tiled: TileLayer<TileWMS>[] = [];
    const vectors: string[] = [];
    for (const name of wmsLayers) {
      const format = formats.get(name);
      if (!format) { vectors.push(name); continue; }
      const key = `${name}@${config.version}`;
      let layer = tileLayersRef.current.get(key);
      if (!layer) {
        layer = new TileLayer({
          preload: 1,
          source: new TileWMS({
            url: "/ows",
            params: {
              PROJECT: config.slug, VERSION: "1.1.1", LAYERS: name, STYLES: "", FORMAT: format,
              TRANSPARENT: format === "image/jpeg" ? "false" : "true",
              TILED: "true", V: config.version,     // TILED=true => cache nginx; V => nowa wersja projektu
            },
            tileGrid, serverType: "qgis", hidpi: false, transition: 0,
          }),
        });
        tileLayersRef.current.set(key, layer);
      }
      tiled.push(layer);
    }
    group.setLayers(new Collection(tiled));
    wmsLayerRef.current?.setVisible(vectors.length > 0);
    wms.updateParams({ LAYERS: vectors.join(","), _t: reloadToken });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wmsLayers, reloadToken, config.slug, config.version]);

  // --- obiekty warstwy edycyjnej (ładowane z API dla bieżącego widoku)
  useEffect(() => {
    const map = mapRef.current;
    const source = editSourceRef.current;
    source.clear();
    if (!map || !editLayerId) return;
    let cancelled = false;
    const load = async () => {
      const extent = map.getView().calculateExtent(map.getSize());
      const fc = await api.features(config.slug, editLayerId, extent, crs);
      if (cancelled) return;
      source.clear();
      source.addFeatures(format.readFeatures({ type: "FeatureCollection", features: fc.features }) as Feature<Geometry>[]);
    };
    load().catch(console.error);
    map.on("moveend", load);
    return () => { cancelled = true; map.un("moveend", load); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editLayerId, reloadToken, config.slug]);

  // --- narzędzia
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const source = editSourceRef.current;
    const interactions: (Draw | Modify | Select | Snap)[] = [];
    const layerInfo = editLayerId ? config.layers[editLayerId] : null;
    const toGeoJSON = (f: Feature<Geometry>) =>
      format.writeGeometryObject(f.getGeometry()!) as unknown as GeoJSONFeature["geometry"];

    let clickKey: EventsKey | null = null;

    if (tool === "identify") {
      const handler = async (evt: { coordinate: number[] }) => {
        const wms = wmsRef.current!;
        const queryable = Object.values(config.layers)
          .filter((l) => l.popup && l.type === "vector" && wmsLayers.includes(l.wms_name))
          .map((l) => l.wms_name);
        if (!queryable.length) return;
        const url = wms.getFeatureInfoUrl(evt.coordinate, map.getView().getResolution()!, crs, {
          INFO_FORMAT: "application/json", QUERY_LAYERS: queryable.join(","), FEATURE_COUNT: 10,
          FI_POINT_TOLERANCE: 12, FI_LINE_TOLERANCE: 8, FI_POLYGON_TOLERANCE: 4, WITH_GEOMETRY: "false",
        });
        if (!url) return;
        const res = await fetch(url, { credentials: "same-origin" });
        if (!res.ok) return;
        const fc = await res.json();
        const first = fc.features?.[0];
        if (!first?.id) return;
        // QGIS zwraca id w postaci "<nazwa_wms>.<pk>"
        const id = String(first.id);
        const dot = id.lastIndexOf(".");
        const lyr = Object.values(config.layers).find((l) => l.wms_name === id.slice(0, dot));
        if (lyr) cbRef.current.onIdentify(lyr.id, id.slice(dot + 1));
      };
      clickKey = map.on("singleclick", handler as never) as EventsKey;
    }

    if (layerInfo && tool === "select") {
      const select = new Select({ layers: (l) => l instanceof VectorLayer, condition: click, style: editStyle });
      select.on("select", (e) => {
        const f = e.selected[0] as Feature<Geometry> | undefined;
        if (f) cbRef.current.onSelect(layerInfo.id, format.writeFeatureObject(f) as unknown as GeoJSONFeature);
      });
      interactions.push(select);
    }

    if (layerInfo && tool === "draw" && layerInfo.perms.insert && layerInfo.geometry_type) {
      const draw = new Draw({ source, type: DRAW_TYPE[layerInfo.geometry_type] });
      draw.on("drawend", (e) => cbRef.current.onDrawn(layerInfo.id, toGeoJSON(e.feature as Feature<Geometry>)));
      interactions.push(draw);
    }

    if (layerInfo && tool === "modify" && layerInfo.perms.update) {
      const modify = new Modify({ source });
      modify.on("modifyend", (e) => {
        for (const f of e.features.getArray() as Feature<Geometry>[]) {
          cbRef.current.onGeometryModified(layerInfo.id, String(f.getId()), toGeoJSON(f));
        }
      });
      interactions.push(modify);
    }

    // Przyciąganie do wierzchołków i krawędzi obiektów warstwy edycyjnej
    if (layerInfo && (tool === "draw" || tool === "modify")) interactions.push(new Snap({ source }));

    interactions.forEach((i) => map.addInteraction(i));
    return () => {
      interactions.forEach((i) => map.removeInteraction(i));
      if (clickKey) unByKey(clickKey);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tool, editLayerId, config.slug, wmsLayers]);

  return <div ref={divRef} className="map" />;
}
