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
import { Draw, Modify, Select, Snap, Translate } from "ol/interaction";
import type Interaction from "ol/interaction/Interaction";
import PointerInteraction from "ol/interaction/Pointer";
import { getCenter } from "ol/extent";
import { click } from "ol/events/condition";
import { ScaleLine, defaults as defaultControls } from "ol/control";
import { Circle, Fill, Stroke, Style } from "ol/style";
import { unByKey } from "ol/Observable";
import type { EventsKey } from "ol/events";
import type Feature from "ol/Feature";
import OlFeature from "ol/Feature";
import { fromExtent as polygonFromExtent } from "ol/geom/Polygon";
import type { Geometry } from "ol/geom";
import { api } from "../api";
import type { Basemap, GeoJSONFeature, ProjectConfig, TreeNode } from "../types";
import { PNG8, basemapLayer, ensureBasemapProjections, tileGridFor } from "../tiles";
import { attributionHtml, projectAttributions } from "../attribution";
import { startMeasure } from "../measure";

// --- Kafle rastrów
// Rastry projektu (skany, mozaiki) idą jako kafle WMS na stałej siatce: te same adresy
// przy każdym oglądaniu, więc serwer (nginx przed QGIS) i przeglądarka mogą je cache'ować.
// Wektory zostają jednym obrazem WMS bez cache — zmieniają się przy edycji.
// Podkłady (ortofoto, topo, OSM...) pochodzą z katalogu Sophii, nie z projektu.

/** Nazwa WMS -> format kafli dla warstw rastrowych i mozaik (pozostałe = wektory). */
export function tileFormats(config: ProjectConfig): Map<string, string> {
  const out = new Map<string, string>();
  for (const l of Object.values(config.layers)) if (l.tile_format) out.set(l.wms_name, l.tile_format);
  const walk = (n: TreeNode) => {
    if (n.kind === "raster_group") out.set(n.name, PNG8);
    n.children.forEach(walk);
  };
  walk(config.tree);
  return out;
}

export type Tool = "identify" | "select" | "draw" | "modify" | "split" | "ring" | "fillring" | "delring"
  | "delpart" | "addpart" | "reshape" | "move" | "rotate" | "copy" | "merge" | "fetch" | "measure-length" | "measure-area";

/** Narzędzia, które klikają w obiekt warstwy edycyjnej (wynik liczy API). */
export type PointTool = "delring" | "delpart";

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
  onSplitLine: (layerId: string, line: GeoJSONFeature["geometry"]) => void;   // narzędzie „Podziel obiekty”
  onRing: (layerId: string, ring: GeoJSONFeature["geometry"], fill: boolean) => void;   // pierścień / wypełniony
  onPointTool: (layerId: string, tool: PointTool, coordinate: number[], tolerance: number) => void;
  onMergePick: (layerId: string, pk: string) => void;   // „Połącz obiekty”: kliknięty obiekt do zestawu
  onAddPart: (layerId: string, part: GeoJSONFeature["geometry"]) => void;
  onReshape: (layerId: string, line: GeoJSONFeature["geometry"]) => void;
  onCopy: (layerId: string, pk: string, geometry: GeoJSONFeature["geometry"]) => void;   // kopia w nowym miejscu
  marked: string[];                                      // obiekty wybrane do połączenia (wyróżnione)
  onFetchClick?: (coordinate: number[]) => void;         // narzędzie pobierania (ULDK…)
  preview?: GeoJSONFeature["geometry"] | null;           // obrys pobranego obiektu przed dodaniem
  printFrame?: [number, number, number] | null;          // obszar wydruku [szer., wys.] w metrach wokół środka widoku, obrót w ° (zegar)
  opacity: Record<string, number>;                       // krycie 0–100: "<slug>/<warstwa WMS>", "bm:<id>"
  mapRef: MutableRefObject<OlMap | null>;
}

const editStyle = new Style({
  stroke: new Stroke({ color: "#d9480f", width: 2 }),
  fill: new Fill({ color: "rgba(217,72,15,0.15)" }),
  image: new Circle({ radius: 6, fill: new Fill({ color: "#d9480f" }), stroke: new Stroke({ color: "#fff", width: 2 }) }),
});

const previewStyle = new Style({
  stroke: new Stroke({ color: "#1c7ed6", width: 2.5, lineDash: [8, 5] }),
  fill: new Fill({ color: "rgba(28,126,214,0.12)" }),
  image: new Circle({ radius: 7, fill: new Fill({ color: "#1c7ed6" }), stroke: new Stroke({ color: "#fff", width: 2 }) }),
});

const frameStyle = new Style({
  stroke: new Stroke({ color: "#1c7ed6", width: 2.5 }),
  fill: new Fill({ color: "rgba(28,126,214,0.06)" }),
});

const splitStyle = new Style({
  stroke: new Stroke({ color: "#d9363e", width: 2, lineDash: [6, 4] }),
  image: new Circle({ radius: 5, fill: new Fill({ color: "#d9363e" }), stroke: new Stroke({ color: "#fff", width: 1.5 }) }),
});

const markStyle = new Style({
  stroke: new Stroke({ color: "#7048e8", width: 3 }),
  fill: new Fill({ color: "rgba(112,72,232,0.25)" }),
  image: new Circle({ radius: 7, fill: new Fill({ color: "#7048e8" }), stroke: new Stroke({ color: "#fff", width: 2 }) }),
});

const ringStyle = new Style({
  stroke: new Stroke({ color: "#d9363e", width: 2, lineDash: [6, 4] }),
  fill: new Fill({ color: "rgba(255,255,255,0.35)" }),
  image: new Circle({ radius: 5, fill: new Fill({ color: "#d9363e" }), stroke: new Stroke({ color: "#fff", width: 1.5 }) }),
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
  const previewSourceRef = useRef(new VectorSource<Feature<Geometry>>());
  const frameSourceRef = useRef(new VectorSource<Feature<Geometry>>());
  const selectRef = useRef<Select | null>(null);
  const editLayerRef = useRef<VectorLayer | null>(null);
  const markedRef = useRef(new Set<string>());
  const cbRef = useRef(props);
  cbRef.current = props;
  const crs = config.crs;
  const format = new GeoJSON({ dataProjection: crs, featureProjection: crs });

  // --- mapa: tworzona raz na projekt
  useEffect(() => {
    const wms = new ImageWMS({
      url: "/ows",
      params: { PROJECT: config.slug, VERSION: "1.1.1", FORMAT: "image/png", TRANSPARENT: "true", LAYERS: "" },
      // jeden obraz wektorów na widok: rozdzielczość 1:1 także na ekranach HiDPI (2× = 4× pikseli do narysowania
      // w QGIS Server przy każdym przesunięciu) i mały zapas wokół widoku — analiza wydajności 22.11, docs/TODO.md
      ratio: 1.1,
      hidpi: false,
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
        editLayerRef.current = new VectorLayer({
          source: editSourceRef.current,
          style: (f) => (markedRef.current.has(String(f.getId())) ? markStyle : editStyle),
        }),
        new VectorLayer({ source: previewSourceRef.current, style: previewStyle }),
        new VectorLayer({ source: frameSourceRef.current, style: frameStyle }),
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
      active.forEach((b, i) => layers[i]?.setOpacity((props.opacity[`bm:${b.id}`] ?? b.opacity * 100) / 100));
      group.setLayers(new Collection(layers));
    })().catch(console.error);
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [basemaps, baseId, overlayIds, config.slug, props.opacity]);

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
      layer.setOpacity((props.opacity[`${config.slug}/${name}`] ?? 100) / 100);
      layer.getSource()?.setAttributions(attributionHtml(projectAttributions(config, [name])));
      tiled.push(layer);
    }
    group.setLayers(new Collection(tiled));
    wms.setAttributions(attributionHtml(projectAttributions(config, vectors)));
    wmsLayerRef.current?.setVisible(vectors.length > 0);
    wms.updateParams({ LAYERS: vectors.join(","), _t: reloadToken });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wmsLayers, reloadToken, config.slug, config.version, props.opacity]);

  // --- obiekty warstwy edycyjnej (ładowane z API dla bieżącego widoku)
  useEffect(() => {
    const map = mapRef.current;
    const source = editSourceRef.current;
    source.clear();
    selectRef.current?.getFeatures().clear();   // zaznaczenie wskazywałoby stary, usunięty obiekt
    if (!map || !editLayerId || !config.layers[editLayerId]?.geometry_type) return;   // bez geometrii: lista w panelu
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

  // --- ramka obszaru wydruku: stały rozmiar w terenie, zawsze na środku widoku
  const { printFrame } = props;
  useEffect(() => {
    const map = mapRef.current;
    const src = frameSourceRef.current;
    src.clear();
    if (!map || !printFrame) return;
    const view = map.getView();
    const f = new OlFeature<Geometry>();
    const update = () => {
      const c = view.getCenter();
      if (!c) return;
      const [w, h, rot] = printFrame;
      const g = polygonFromExtent([c[0] - w / 2, c[1] - h / 2, c[0] + w / 2, c[1] + h / 2]);
      // QGIS obraca treść mapy zgodnie z zegarem — obszar w terenie obraca się przeciwnie (OL: dodatni kąt = przeciwnie)
      if (rot) g.rotate((rot * Math.PI) / 180, c);
      f.setGeometry(g);
    };
    update();
    src.addFeature(f);
    view.on("change:center", update);
    return () => { view.un("change:center", update); src.clear(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [printFrame?.[0], printFrame?.[1], printFrame?.[2], config.slug]);

  // --- podgląd obiektu z narzędzia pobierania
  const { preview } = props;
  useEffect(() => {
    const src = previewSourceRef.current;
    src.clear();
    if (!preview) return;
    const f = format.readFeature({ type: "Feature", geometry: preview, properties: {} }) as Feature<Geometry>;
    src.addFeature(f);
    const map = mapRef.current;
    const ext = f.getGeometry()?.getExtent();
    if (map && ext) {
      const view = map.getView();
      const visible = view.calculateExtent(map.getSize());
      const inside = ext[0] >= visible[0] && ext[1] >= visible[1] && ext[2] <= visible[2] && ext[3] <= visible[3];
      if (!inside) view.fit(ext, { padding: [80, 80, 80, 80], maxZoom: view.getZoom(), duration: 250 });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preview]);

  // --- narzędzia
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const source = editSourceRef.current;
    const interactions: Interaction[] = [];
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

    if (tool === "fetch") {
      clickKey = map.on("singleclick", ((evt: { coordinate: number[] }) => cbRef.current.onFetchClick?.(evt.coordinate)) as never) as EventsKey;
    }

    if (layerInfo && tool === "select") {
      const select = new Select({ layers: (l) => l instanceof VectorLayer, condition: click, style: editStyle });
      select.on("select", (e) => {
        const f = e.selected[0] as Feature<Geometry> | undefined;
        if (f) cbRef.current.onSelect(layerInfo.id, format.writeFeatureObject(f) as unknown as GeoJSONFeature);
      });
      interactions.push(select);
      selectRef.current = select;
    }

    // W trybie zmiany geometrii kliknięcie (bez przeciągania) też otwiera obiekt w formularzu
    if (layerInfo && tool === "modify") {
      const handler = (evt: { pixel: number[] }) => {
        const f = map.forEachFeatureAtPixel(evt.pixel, (x) => x as Feature<Geometry>,
          { layerFilter: (l) => l instanceof VectorLayer && l.getSource() === source, hitTolerance: 4 });
        if (f) cbRef.current.onSelect(layerInfo.id, format.writeFeatureObject(f) as unknown as GeoJSONFeature);
      };
      clickKey = map.on("singleclick", handler as never) as EventsKey;
    }

    if (layerInfo && tool === "draw" && layerInfo.perms.insert && layerInfo.geometry_type) {
      const draw = new Draw({ source, type: DRAW_TYPE[layerInfo.geometry_type] });
      draw.on("drawend", (e) => cbRef.current.onDrawn(layerInfo.id, toGeoJSON(e.feature as Feature<Geometry>)));
      interactions.push(draw);
    }

    // Podział: linia szkicu (bez zapisu do warstwy) — geometrię części liczy API (PostGIS)
    if (layerInfo && tool === "split" && layerInfo.perms.update && layerInfo.perms.insert
      && (layerInfo.geometry_type === "Polygon" || layerInfo.geometry_type === "Line")) {
      const draw = new Draw({ type: "LineString", style: splitStyle });
      draw.on("drawend", (e) => cbRef.current.onSplitLine(layerInfo.id, toGeoJSON(e.feature as Feature<Geometry>)));
      interactions.push(draw);
    }

    // Pierścień (dziura) i pierścień wypełniony: szkic poligonu, obiekt docelowy wskazuje API
    if (layerInfo && (tool === "ring" || tool === "fillring") && layerInfo.geometry_type === "Polygon"
      && layerInfo.perms.update && (tool === "ring" || layerInfo.perms.insert)) {
      const draw = new Draw({ type: "Polygon", style: ringStyle });
      draw.on("drawend", (e) => cbRef.current.onRing(layerInfo.id, toGeoJSON(e.feature as Feature<Geometry>), tool === "fillring"));
      interactions.push(draw);
    }

    // Kliknięcie w obiekt: usuń pierścień / usuń część (tolerancja ~8 px w jednostkach mapy)
    if (layerInfo && (tool === "delring" || tool === "delpart") && layerInfo.perms.update) {
      const handler = (evt: { coordinate: number[] }) => cbRef.current.onPointTool(
        layerInfo.id, tool, evt.coordinate, (map.getView().getResolution() ?? 1) * 8);
      clickKey = map.on("singleclick", handler as never) as EventsKey;
    }

    // Połącz obiekty: kliknięcia dodają / zdejmują obiekty z zestawu
    if (layerInfo && tool === "merge" && layerInfo.perms.update && layerInfo.perms.delete) {
      const handler = (evt: { pixel: number[] }) => {
        const f = map.forEachFeatureAtPixel(evt.pixel, (x) => x as Feature<Geometry>,
          { layerFilter: (l) => l === editLayerRef.current, hitTolerance: 4 });
        if (f) cbRef.current.onMergePick(layerInfo.id, String(f.getId()));
      };
      clickKey = map.on("singleclick", handler as never) as EventsKey;
    }

    // Przesuń obiekt: przeciągnięcie całego obiektu, zapis jak przy zmianie wierzchołków
    if (layerInfo && tool === "move" && layerInfo.perms.update) {
      const translate = new Translate({ layers: [editLayerRef.current!], hitTolerance: 4 });
      translate.on("translateend", (e) => {
        for (const f of e.features.getArray() as Feature<Geometry>[]) {
          cbRef.current.onGeometryModified(layerInfo.id, String(f.getId()), toGeoJSON(f));
        }
      });
      interactions.push(translate);
    }

    // Dodaj część: szkic typu warstwy, część trafia do obiektu otwartego w formularzu
    if (layerInfo && tool === "addpart" && layerInfo.perms.update && layerInfo.multi && layerInfo.geometry_type) {
      const draw = new Draw({ type: DRAW_TYPE[layerInfo.geometry_type], style: ringStyle });
      draw.on("drawend", (e) => cbRef.current.onAddPart(layerInfo.id, toGeoJSON(e.feature as Feature<Geometry>)));
      interactions.push(draw);
    }

    // Przekształć: linia przecinająca granicę dwa razy; wynik liczy API
    if (layerInfo && tool === "reshape" && layerInfo.perms.update
      && (layerInfo.geometry_type === "Polygon" || layerInfo.geometry_type === "Line")) {
      const draw = new Draw({ type: "LineString", style: splitStyle });
      draw.on("drawend", (e) => cbRef.current.onReshape(layerInfo.id, toGeoJSON(e.feature as Feature<Geometry>)));
      interactions.push(draw);
    }

    // Kopiuj: przeciągnięcie zostawia oryginał na miejscu, w nowym miejscu powstaje kopia
    if (layerInfo && tool === "copy" && layerInfo.perms.insert) {
      const originals = new Map<Feature<Geometry>, Geometry>();
      const translate = new Translate({ layers: [editLayerRef.current!], hitTolerance: 4 });
      translate.on("translatestart", (e) => {
        originals.clear();
        for (const f of e.features.getArray() as Feature<Geometry>[]) originals.set(f, f.getGeometry()!.clone());
      });
      translate.on("translateend", (e) => {
        for (const f of e.features.getArray() as Feature<Geometry>[]) {
          const moved = toGeoJSON(f);
          const orig = originals.get(f);
          if (orig) f.setGeometry(orig);
          cbRef.current.onCopy(layerInfo.id, String(f.getId()), moved);
        }
      });
      interactions.push(translate);
    }

    // Obróć: przeciąganie wokół środka obiektu, Shift = co 15°; zapis po puszczeniu
    if (layerInfo && tool === "rotate" && layerInfo.perms.update
      && (layerInfo.geometry_type === "Polygon" || layerInfo.geometry_type === "Line")) {
      let target: Feature<Geometry> | null = null;
      let orig: Geometry | null = null;
      let center = [0, 0];
      let start = 0;
      let turned = false;
      const angleAt = (c: number[]) => Math.atan2(c[1] - center[1], c[0] - center[0]);
      const rotate = new PointerInteraction({
        handleDownEvent: (e) => {
          const f = map.forEachFeatureAtPixel(e.pixel, (x) => x as Feature<Geometry>,
            { layerFilter: (l) => l === editLayerRef.current, hitTolerance: 4 });
          if (!f?.getGeometry()) return false;
          target = f;
          orig = f.getGeometry()!.clone();
          center = getCenter(orig.getExtent());
          start = angleAt(e.coordinate);
          turned = false;
          return true;
        },
        handleDragEvent: (e) => {
          if (!target || !orig) return;
          let a = angleAt(e.coordinate) - start;
          if ((e.originalEvent as PointerEvent).shiftKey) a = Math.round(a / (Math.PI / 12)) * (Math.PI / 12);
          const g = orig.clone();
          g.rotate(a, center);
          target.setGeometry(g);
          turned = true;
        },
        handleUpEvent: () => {
          if (target && turned) cbRef.current.onGeometryModified(layerInfo.id, String(target.getId()), toGeoJSON(target));
          target = null;
          return false;
        },
      });
      interactions.push(rotate);
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
    if (layerInfo && ["draw", "modify", "split", "ring", "fillring", "addpart", "reshape"].includes(tool)) {
      interactions.push(new Snap({ source }));
    }

    // Szkic: Esc przerywa, Backspace cofa ostatni wierzchołek (poza polami formularza)
    const draws = interactions.filter((i): i is Draw => i instanceof Draw);
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName))) return;
      if (e.key === "Escape") draws.forEach((d) => d.abortDrawing());
      else if (e.key === "Backspace") { draws.forEach((d) => d.removeLastPoint()); e.preventDefault(); }
    };
    if (draws.length) document.addEventListener("keydown", onKey);

    interactions.forEach((i) => map.addInteraction(i));
    return () => {
      interactions.forEach((i) => map.removeInteraction(i));
      document.removeEventListener("keydown", onKey);
      if (clickKey) unByKey(clickKey);
      selectRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tool, editLayerId, config.slug, wmsLayers]);

  // --- pomiar długości i powierzchni (niezależny od warstwy edycyjnej; działa też bez projektu)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || (tool !== "measure-length" && tool !== "measure-area")) return;
    return startMeasure(map, tool === "measure-area" ? "area" : "length", editLayerId ? editSourceRef.current : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tool, editLayerId, config.slug]);

  // --- wyróżnienie obiektów wybranych do połączenia
  const { marked } = props;
  useEffect(() => {
    markedRef.current = new Set(marked);
    editLayerRef.current?.changed();
  }, [marked]);

  return <div ref={divRef} className="map" />;
}
