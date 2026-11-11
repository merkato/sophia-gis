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
