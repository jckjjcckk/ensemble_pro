import type { ReactNode } from 'react'
import type { AnnotationKind } from '../shared'

/** Hand-drawn icon set: 24 grid, one 1.6 stroke, round joins, no fills. */
function Svg({ children, size = 20 }: { children: ReactNode; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className="x4-icon"
    >
      {children}
    </svg>
  )
}

type P = { size?: number }

export const IconPencil = ({ size }: P) => (
  <Svg size={size}>
    <path d="M4.5 19.5l1-4.2L15.6 5.2a1.9 1.9 0 0 1 2.7 0l.5.5a1.9 1.9 0 0 1 0 2.7L8.7 18.5z" />
    <path d="M14 6.8l3.2 3.2" />
  </Svg>
)

export const IconCut = ({ size }: P) => (
  <Svg size={size}>
    <circle cx="6.5" cy="6.5" r="2.5" />
    <circle cx="6.5" cy="17.5" r="2.5" />
    <path d="M8.6 8l11 9.5M8.6 16l11-9.5" />
  </Svg>
)

export const IconMic = ({ size }: P) => (
  <Svg size={size}>
    <rect x="9" y="3.5" width="6" height="11" rx="3" />
    <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v2.5" />
  </Svg>
)

export const IconText = ({ size }: P) => (
  <Svg size={size}>
    <path d="M5 6h14M12 6v13M9.5 19h5" />
  </Svg>
)

export const IconDynamic = ({ size }: P) => (
  <Svg size={size}>
    <path d="M20 6.5L5 12l15 5.5" />
  </Svg>
)

export const IconBowing = ({ size }: P) => (
  <Svg size={size}>
    <path d="M6 18V7h12v11" />
    <path d="M6 9h12" />
  </Svg>
)

export const IconBreath = ({ size }: P) => (
  <Svg size={size}>
    <path d="M12 7a2 2 0 1 1 0 4c0 2.5-1 4.5-3 6" />
  </Svg>
)

export const IconPlay = ({ size }: P) => (
  <Svg size={size}>
    <path d="M7.5 5.5v13l11-6.5z" />
  </Svg>
)

export const IconPause = ({ size }: P) => (
  <Svg size={size}>
    <path d="M8.5 5.5v13M15.5 5.5v13" />
  </Svg>
)

export const IconChevronLeft = ({ size }: P) => (
  <Svg size={size}>
    <path d="M14.5 5.5L8 12l6.5 6.5" />
  </Svg>
)

export const IconChevronRight = ({ size }: P) => (
  <Svg size={size}>
    <path d="M9.5 5.5L16 12l-6.5 6.5" />
  </Svg>
)

export const IconChevronDown = ({ size }: P) => (
  <Svg size={size}>
    <path d="M6 9.5l6 6 6-6" />
  </Svg>
)

export const IconMetronome = ({ size }: P) => (
  <Svg size={size}>
    <path d="M9.5 3.5h5L18 20.5H6z" />
    <path d="M12 15.5l5-8.5M8 17h8" />
  </Svg>
)

export const IconListen = ({ size }: P) => (
  <Svg size={size}>
    <path d="M3.5 12h1.5M7.5 8.5v7M11.5 5.5v13M15.5 8.5v7M19.5 11v2" />
  </Svg>
)

export const IconHistory = ({ size }: P) => (
  <Svg size={size}>
    <path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3" />
    <path d="M4.5 4.5v3.5H8M12 8v4.5l3 2" />
  </Svg>
)

export const IconCamera = ({ size }: P) => (
  <Svg size={size}>
    <path d="M3.5 8.5h3.2l1.8-2.5h7l1.8 2.5h3.2v10.5h-17z" />
    <circle cx="12" cy="13.5" r="3.3" />
  </Svg>
)

export const IconTrash = ({ size }: P) => (
  <Svg size={size}>
    <path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13M10.5 11v5.5M13.5 11v5.5" />
  </Svg>
)

export const IconWarn = ({ size }: P) => (
  <Svg size={size}>
    <path d="M12 4l9 16H3z" />
    <path d="M12 10v4.5M12 17.2v.1" />
  </Svg>
)

export const IconCheck = ({ size }: P) => (
  <Svg size={size}>
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </Svg>
)

export const IconMoon = ({ size }: P) => (
  <Svg size={size}>
    <path d="M19.5 14.5A7.5 7.5 0 1 1 9.5 4.5a6 6 0 0 0 10 10z" />
  </Svg>
)

export const IconSun = ({ size }: P) => (
  <Svg size={size}>
    <circle cx="12" cy="12" r="3.8" />
    <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4" />
  </Svg>
)

export const IconPlus = ({ size }: P) => (
  <Svg size={size}>
    <path d="M12 5.5v13M5.5 12h13" />
  </Svg>
)

export const IconMinus = ({ size }: P) => (
  <Svg size={size}>
    <path d="M5.5 12h13" />
  </Svg>
)

export const IconClose = ({ size }: P) => (
  <Svg size={size}>
    <path d="M6.5 6.5l11 11M17.5 6.5l-11 11" />
  </Svg>
)

export const IconList = ({ size }: P) => (
  <Svg size={size}>
    <path d="M9 7h10.5M9 12h10.5M9 17h10.5M4.5 7h.5M4.5 12h.5M4.5 17h.5" />
  </Svg>
)

export const IconUndo = ({ size }: P) => (
  <Svg size={size}>
    <path d="M9 6.5L4.5 11 9 15.5" />
    <path d="M4.5 11H15a4.5 4.5 0 0 1 0 9h-3" />
  </Svg>
)

export const IconLoop = ({ size }: P) => (
  <Svg size={size}>
    <path d="M7 4.5v15M17 4.5v15M7 4.5h3M7 19.5h3M17 4.5h-3M17 19.5h-3" />
  </Svg>
)

export const IconGrip = ({ size }: P) => (
  <Svg size={size}>
    <path d="M9 6.5h.01M15 6.5h.01M9 12h.01M15 12h.01M9 17.5h.01M15 17.5h.01" />
  </Svg>
)

export function KindIcon({ kind, size }: { kind: AnnotationKind; size?: number }) {
  switch (kind) {
    case 'cut':
      return <IconCut size={size} />
    case 'voice':
      return <IconMic size={size} />
    case 'text':
      return <IconText size={size} />
    case 'dynamic':
      return <IconDynamic size={size} />
    case 'bowing':
      return <IconBowing size={size} />
    case 'breath':
      return <IconBreath size={size} />
    default:
      return <IconPencil size={size} />
  }
}
