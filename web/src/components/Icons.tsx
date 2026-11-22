import type { ReactNode, SVGProps } from "react";

// Ikony narzędzi w stylu QGIS: te same metafory i kolory (żółty ołówek edycji, zielone obiekty
// z gwiazdką „dodaj”, czerwone węzły narzędzia wierzchołków, niebieskie „i” identyfikacji),
// narysowane od nowa — własne SVG, bez kopiowania grafik QGIS (GPL).
// Kolory stałe: czytelne na jasnym i ciemnym tle paska.

const C = {
  line: "#3c4a5c", lineDark: "#9fb0c4", green: "#5aa63c", greenFill: "#b9e19a",
  yellow: "#f2c230", yellowDark: "#b58a00", red: "#d9363e", blue: "#2f7bd9", gray: "#8a96a3",
};

type P = SVGProps<SVGSVGElement>;

function Svg({ children, ...p }: P & { children: ReactNode }) {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true" focusable="false" {...p}>
      {children}
    </svg>
  );
}

/** Gwiazdka „dodaj” w prawym górnym rogu (jak w QGIS przy dodawaniu obiektu). */
const Spark = () => (
  <path d="M18.5 1.8l.9 2.2 2.3.2-1.8 1.5.6 2.3-2-1.2-2 1.2.6-2.3-1.8-1.5 2.3-.2z"
    fill={C.yellow} stroke={C.yellowDark} strokeWidth=".6" />
);

/** Ołówek — przełączanie edycji warstwy. */
export const IconEdit = (p: P) => (
  <Svg {...p}>
    <path d="M4 20l1.2-4.6L16.6 4a1.8 1.8 0 012.6 0l.8.8a1.8 1.8 0 010 2.6L8.6 18.8z" fill={C.yellow} stroke={C.yellowDark} strokeWidth="1.2" />
    <path d="M14.6 6l3.4 3.4" stroke={C.yellowDark} strokeWidth="1.2" />
    <path d="M4 20l1.2-4.6 3.4 3.4z" fill="#f6dfb0" stroke={C.yellowDark} strokeWidth="1.2" />
  </Svg>
);

/** Identyfikacja obiektów: niebieskie „i” z kursorem. */
export const IconIdentify = (p: P) => (
  <Svg {...p}>
    <circle cx="10" cy="10" r="7.5" fill={C.blue} />
    <path d="M10 9v5" stroke="#fff" strokeWidth="2" />
    <circle cx="10" cy="6.2" r="1.2" fill="#fff" />
    <path d="M14.5 13.5l6 2.4-2.6 1 2.4 2.4-1.2 1.2-2.4-2.4-1 2.6z" fill="#fff" stroke={C.line} strokeWidth="1" />
  </Svg>
);

/** Zaznacz obiekt: przerywany żółty prostokąt + strzałka. */
export const IconSelect = (p: P) => (
  <Svg {...p}>
    <rect x="2.5" y="3.5" width="14" height="11" fill={C.yellow} fillOpacity=".35" stroke={C.yellowDark} strokeWidth="1.2" strokeDasharray="2.2 1.6" />
    <path d="M11 9l9.5 4-4 1.4 3.6 3.6-1.8 1.8-3.6-3.6L13.3 20z" fill="#fff" stroke={C.line} strokeWidth="1.2" />
  </Svg>
);

/** Dodaj obiekt punktowy. */
export const IconAddPoint = (p: P) => (
  <Svg {...p}>
    <circle cx="9.5" cy="14.5" r="5" fill={C.greenFill} stroke={C.green} strokeWidth="1.6" />
    <circle cx="9.5" cy="14.5" r="1.8" fill={C.green} />
    <Spark />
  </Svg>
);

/** Dodaj obiekt liniowy. */
export const IconAddLine = (p: P) => (
  <Svg {...p}>
    <path d="M2.5 19.5l5-7 5 3.5 4.5-7" stroke={C.green} strokeWidth="2" />
    {[[2.5, 19.5], [7.5, 12.5], [12.5, 16], [17, 9]].map(([x, y]) => (
      <rect key={`${x}`} x={x - 1.5} y={y - 1.5} width="3" height="3" fill="#fff" stroke={C.line} strokeWidth="1" />
    ))}
    <Spark />
  </Svg>
);

/** Dodaj obiekt poligonowy. */
export const IconAddPolygon = (p: P) => (
  <Svg {...p}>
    <path d="M3 18.5L5 8.5l7-2.5 4 7-3 6.5z" fill={C.greenFill} stroke={C.green} strokeWidth="1.6" />
    <Spark />
  </Svg>
);

/** Narzędzie wierzchołków (zmiana geometrii). */
export const IconVertex = (p: P) => (
  <Svg {...p}>
    <path d="M3.5 18.5l2-11 9-3 5.5 8-6 7.5z" fill={C.greenFill} fillOpacity=".55" stroke={C.green} strokeWidth="1.4" />
    {[[3.5, 18.5], [5.5, 7.5], [14.5, 4.5], [14, 20]].map(([x, y]) => (
      <rect key={`${x}-${y}`} x={x - 1.6} y={y - 1.6} width="3.2" height="3.2" fill="#fff" stroke={C.line} strokeWidth="1" />
    ))}
    <rect x="18" y="10.5" width="4" height="4" fill={C.red} stroke="#8c1d22" strokeWidth="1" />
  </Svg>
);

/** Podziel obiekty: dwie części poligonu rozcięte czerwoną linią. */
export const IconSplit = (p: P) => (
  <Svg {...p}>
    <path d="M3 18.5l1.5-11 6.5-2.6 1.6 15.6z" fill={C.greenFill} fillOpacity=".55" stroke={C.green} strokeWidth="1.4" />
    <path d="M13.4 4.6l6.1 2.6 1.5 10.6-6 2.8z" fill={C.greenFill} fillOpacity=".55" stroke={C.green} strokeWidth="1.4" />
    <path d="M12.2 1.8l.9 20.4" stroke={C.red} strokeWidth="1.6" strokeDasharray="2.6 1.8" />
  </Svg>
);

const Hole = ({ fill = "#fff" }: { fill?: string }) => (
  <path d="M9 10.5l4.5-1.5 2 4-3.5 3-3.5-1.5z" fill={fill} stroke={C.green} strokeWidth="1.2" />
);
const Outer = () => <path d="M3 18l2-12 9-3 7 7-3 10z" fill={C.greenFill} fillOpacity=".55" stroke={C.green} strokeWidth="1.4" />;

/** Dodaj pierścień: poligon z dziurą i gwiazdką. */
export const IconRing = (p: P) => (
  <Svg {...p}><Outer /><Hole /><Spark /></Svg>
);

/** Wypełnij pierścień: dziura wypełniona nowym (żółtym) obiektem. */
export const IconFillRing = (p: P) => (
  <Svg {...p}><Outer /><Hole fill={C.yellow} /><Spark /></Svg>
);

/** Usuń pierścień: dziura z czerwonym krzyżykiem. */
export const IconDeleteRing = (p: P) => (
  <Svg {...p}>
    <Outer /><Hole />
    <path d="M16.5 15.5l5 5M21.5 15.5l-5 5" stroke={C.red} strokeWidth="1.8" />
  </Svg>
);

/** Usuń część: dwie części, jedna przekreślona. */
export const IconDeletePart = (p: P) => (
  <Svg {...p}>
    <path d="M2.5 14l3-8 6 2-1 8z" fill={C.greenFill} fillOpacity=".55" stroke={C.green} strokeWidth="1.4" />
    <path d="M13 12l6-3 3 7-6 4z" fill="none" stroke={C.gray} strokeWidth="1.2" strokeDasharray="2 1.6" />
    <path d="M14.5 10.5l6 8M20.5 10.5l-6 8" stroke={C.red} strokeWidth="1.8" />
  </Svg>
);

/** Przesuń obiekt: poligon i strzałki w cztery strony. */
export const IconMove = (p: P) => (
  <Svg {...p}>
    <path d="M6 15l1.5-7 7-1.5 1.5 6.5-5 4z" fill={C.greenFill} fillOpacity=".55" stroke={C.green} strokeWidth="1.4" />
    <path d="M12 1.5v6M12 1.5l-2 2M12 1.5l2 2M12 22.5v-4M12 22.5l-2-2M12 22.5l2-2M1.5 12h3.5M1.5 12l2-2M1.5 12l2 2M22.5 12h-5M22.5 12l-2-2M22.5 12l-2 2"
      stroke={C.line} strokeWidth="1.3" />
  </Svg>
);

/** Połącz obiekty: dwa poligony złączone w jeden obrys. */
export const IconMerge = (p: P) => (
  <Svg {...p}>
    <path d="M2.5 17l1.5-10 8-1v12z" fill={C.greenFill} fillOpacity=".55" />
    <path d="M12 6l7.5 2 1.5 8.5-9 1.5z" fill={C.greenFill} fillOpacity=".55" />
    <path d="M12 6v12" stroke={C.green} strokeWidth="1" strokeDasharray="1.6 1.4" />
    <path d="M2.5 17l1.5-10 8-1 7.5 2 1.5 8.5-9 1.5z" fill="none" stroke={C.green} strokeWidth="1.6" />
    <path d="M9 12h6M13 10l2 2-2 2" stroke={C.blue} strokeWidth="1.4" />
  </Svg>
);

/** Dodaj część: dwie części, nowa z gwiazdką. */
export const IconAddPart = (p: P) => (
  <Svg {...p}>
    <path d="M2.5 15l3-8 6 2-1 8z" fill={C.greenFill} fillOpacity=".55" stroke={C.green} strokeWidth="1.4" />
    <path d="M13 13l5-3 3 7-6 3z" fill={C.greenFill} stroke={C.green} strokeWidth="1.4" />
    <Spark />
  </Svg>
);

/** Przekształć obiekt: poligon z czerwoną linią zmieniającą granicę. */
export const IconReshape = (p: P) => (
  <Svg {...p}>
    <path d="M3 19l2-12 9-3 7 7-4 9z" fill={C.greenFill} fillOpacity=".55" stroke={C.green} strokeWidth="1.4" />
    <path d="M8.5 5.5c1 4.5 6 6.5 11 6" stroke={C.red} strokeWidth="1.8" />
    <circle cx="8.5" cy="5.5" r="1.4" fill={C.red} /><circle cx="19.5" cy="11.5" r="1.4" fill={C.red} />
  </Svg>
);

/** Obróć obiekt: poligon i łuk ze strzałką. */
export const IconRotate = (p: P) => (
  <Svg {...p}>
    <path d="M8 16l1-6.5 6.5-1 1.5 6z" fill={C.greenFill} fillOpacity=".55" stroke={C.green} strokeWidth="1.4" />
    <path d="M20 9.5A8.5 8.5 0 1 0 19 17" stroke={C.line} strokeWidth="1.5" />
    <path d="M20.5 5.5l-.5 4-4-.8" stroke={C.line} strokeWidth="1.5" />
  </Svg>
);

/** Kopiuj obiekt: dwa nakładające się poligony. */
export const IconCopy = (p: P) => (
  <Svg {...p}>
    <path d="M2.5 13l2-8 7-1 1 8z" fill="none" stroke={C.gray} strokeWidth="1.3" strokeDasharray="2 1.5" />
    <path d="M9.5 20l2-8 7-1 2.5 8z" fill={C.greenFill} fillOpacity=".7" stroke={C.green} strokeWidth="1.4" />
    <path d="M8.5 9.5l3 2.5" stroke={C.blue} strokeWidth="1.4" />
  </Svg>
);

/** Cofnij: zakręcona strzałka w lewo. */
export const IconUndo = (p: P) => (
  <Svg {...p}>
    <path d="M8.5 7.5H15a5.5 5.5 0 010 11H8" stroke={C.blue} strokeWidth="1.9" />
    <path d="M11.5 3.5l-4 4 4 4" stroke={C.blue} strokeWidth="1.9" />
  </Svg>
);

/** Usuń zaznaczony obiekt. */
export const IconDelete = (p: P) => (
  <Svg {...p}>
    <path d="M5 7h14l-1.2 13a1.5 1.5 0 01-1.5 1.4H7.7a1.5 1.5 0 01-1.5-1.4z" fill="#f3d1d3" stroke={C.red} strokeWidth="1.4" />
    <path d="M3.5 7h17M9 7V4.5h6V7" stroke={C.red} strokeWidth="1.4" />
    <path d="M10 10.5v7M14 10.5v7" stroke={C.red} strokeWidth="1.2" />
  </Svg>
);

/** Dodaj rekord (tabela bez geometrii). */
export const IconAddRecord = (p: P) => (
  <Svg {...p}>
    <rect x="2.5" y="4.5" width="15" height="14" rx="1" fill="#fff" stroke={C.line} strokeWidth="1.2" />
    <path d="M2.5 9h15M2.5 13.5h15M8 4.5v14" stroke={C.gray} strokeWidth="1" />
    <circle cx="18" cy="17.5" r="4.5" fill={C.green} />
    <path d="M18 15v5M15.5 17.5h5" stroke="#fff" strokeWidth="1.8" />
  </Svg>
);

/** Wydruk widoku mapy. */
export const IconPrint = (p: P) => (
  <Svg {...p}>
    <rect x="6" y="2.5" width="12" height="6" fill="#fff" stroke={C.line} strokeWidth="1.2" />
    <rect x="2.5" y="8" width="19" height="9" rx="1.5" fill="#dfe6ee" stroke={C.line} strokeWidth="1.2" />
    <rect x="6" y="13.5" width="12" height="8" fill="#fff" stroke={C.line} strokeWidth="1.2" />
    <path d="M8 16.5h8M8 19h6" stroke={C.blue} strokeWidth="1.1" />
    <circle cx="18.5" cy="11" r="1" fill={C.green} />
  </Svg>
);

/** Pomiar długości: linijka z łamaną. */
export const IconMeasureLength = (p: P) => (
  <Svg {...p}>
    <rect x="2" y="15" width="20" height="6" rx="1" fill="#f6dfb0" stroke={C.yellowDark} strokeWidth="1.1" />
    <path d="M5 15v2.5M8 15v1.6M11 15v2.5M14 15v1.6M17 15v2.5M20 15v1.6" stroke={C.yellowDark} strokeWidth="1" />
    <path d="M3.5 11l5-6 5 4 7-6" stroke={C.red} strokeWidth="1.6" />
    <circle cx="3.5" cy="11" r="1.4" fill={C.red} /><circle cx="20.5" cy="3" r="1.4" fill={C.red} />
  </Svg>
);

/** Pomiar powierzchni: poligon z linijką. */
export const IconMeasureArea = (p: P) => (
  <Svg {...p}>
    <path d="M4 12l3-8 9 1 4 7-6 2z" fill="#ffd8a8" fillOpacity=".8" stroke={C.red} strokeWidth="1.4" strokeDasharray="2.5 1.8" />
    <rect x="2" y="16" width="20" height="5" rx="1" fill="#f6dfb0" stroke={C.yellowDark} strokeWidth="1.1" />
    <path d="M5 16v2M8 16v1.4M11 16v2M14 16v1.4M17 16v2M20 16v1.4" stroke={C.yellowDark} strokeWidth="1" />
  </Svg>
);

/** Tabela atrybutów. */
export const IconTable = (p: P) => (
  <Svg {...p}>
    <rect x="2.5" y="4" width="19" height="16" rx="1.2" fill="#fff" stroke={C.line} strokeWidth="1.2" />
    <rect x="2.5" y="4" width="19" height="4" fill={C.blue} fillOpacity=".25" stroke={C.line} strokeWidth="1.2" />
    <path d="M2.5 12h19M2.5 16h19M9 8v12M15 8v12" stroke={C.gray} strokeWidth="1" />
  </Svg>
);

/** Panel warstw (pokaż / ukryj). */
export const IconLayers = (p: P) => (
  <Svg {...p}>
    <path d="M12 3l9 4.5-9 4.5-9-4.5z" fill={C.greenFill} stroke={C.green} strokeWidth="1.2" />
    <path d="M3 12l9 4.5 9-4.5" stroke={C.blue} strokeWidth="1.4" />
    <path d="M3 16.5L12 21l9-4.5" stroke={C.yellowDark} strokeWidth="1.4" />
  </Svg>
);

/** Strzałka „pobierz” (niebieska, prawy dolny róg). */
const Fetch = () => (
  <>
    <circle cx="18" cy="17.5" r="5" fill={C.blue} />
    <path d="M18 14.5v5.2M15.8 17.6l2.2 2.2 2.2-2.2" stroke="#fff" strokeWidth="1.6" />
  </>
);

/** Pobierz działkę z usługi (ULDK): obrys działki z punktami granicznymi + strzałka. */
export const IconFetchParcel = (p: P) => (
  <Svg {...p}>
    <path d="M2.5 15.5L4.5 4l9-1.5 1.5 7.5" fill="#f6e7c8" stroke="#a5681c" strokeWidth="1.4" />
    <path d="M2.5 15.5l9 1" stroke="#a5681c" strokeWidth="1.4" />
    {[[2.5, 15.5], [4.5, 4], [13.5, 2.5]].map(([x, y]) => <circle key={`${x}`} cx={x} cy={y} r="1.4" fill="#a5681c" />)}
    <Fetch />
  </Svg>
);

/** Pobierz budynek z usługi (ULDK): obrys budynku + strzałka. */
export const IconFetchBuilding = (p: P) => (
  <Svg {...p}>
    <path d="M2.5 11L9 4.5l6.5 6.5" stroke="#a83a2f" strokeWidth="1.5" />
    <path d="M4.5 9.5V19h7.5" fill="#f1d3cd" stroke="#a83a2f" strokeWidth="1.4" />
    <path d="M13.5 9.5v2" stroke="#a83a2f" strokeWidth="1.4" />
    <rect x="7.5" y="13" width="3" height="6" fill="#a83a2f" />
    <Fetch />
  </Svg>
);

export const GEOMETRY_ICON = { Point: IconAddPoint, Line: IconAddLine, Polygon: IconAddPolygon } as const;
