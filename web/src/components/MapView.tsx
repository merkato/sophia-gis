import { useEffect, useRef, type MutableRefObject } from "react";
import OlMap from "ol/Map";
import View from "ol/View";
import ImageLayer from "ol/layer/Image";
import TileLayer from "ol/layer/Tile";
import VectorLayer from "ol/layer/Vector";
import ImageWMS from "ol/source/ImageWMS";
import OSM from "ol/source/OSM";
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
import type { GeoJSONFeature, ProjectConfig } from "../types";

export type Tool = "identify" | "select" | "draw" | "modify";

interface Props {
  config: ProjectConfig;
  wmsLayers: string[];               // kolejność rysowania: od spodu do wierzchu
  editLayerId: string | null;
  tool: Tool;
  reloadToken: number;               // zmiana => przeładuj obiekty warstwy edycyjnej i WMS
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
    const map = new OlMap({
      target: divRef.current!,
      controls: defaultControls().extend([new ScaleLine()]),
      layers: [
        new TileLayer({ source: new OSM(), properties: { name: "basemap" } }),
        new ImageLayer({ source: wms }),
        new VectorLayer({ source: editSourceRef.current, style: editStyle }),
      ],
      view: new View({ projection: crs, center: [500000, 400000], zoom: 6 }),
    });
    if (config.extent) map.getView().fit(config.extent, { padding: [20, 20, 20, 20] });
    mapRef.current = map;
    return () => { map.setTarget(undefined); mapRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.slug]);

  // --- widoczne warstwy WMS
  useEffect(() => {
    const wms = wmsRef.current;
    if (!wms) return;
    const layer = mapRef.current?.getLayers().item(1);
    layer?.setVisible(wmsLayers.length > 0);
    wms.updateParams({ LAYERS: wmsLayers.join(","), _t: reloadToken });
  }, [wmsLayers, reloadToken, mapRef]);

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
