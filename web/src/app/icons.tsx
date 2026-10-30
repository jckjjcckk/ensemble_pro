import type { ReactNode, SVGProps } from 'react'

type P = Omit<SVGProps<SVGSVGElement>, 'children'> & { size?: number }

function Svg({ size = 24, children, ...rest }: P & { children: ReactNode }) {
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true" focusable="false" {...rest}
    >
      {children}
    </svg>
  )
}

export const ILibrary = (p: P) => <Svg {...p}><path d="M4 4h3.5v16H4zM9.5 4H13v16H9.5z" /><path d="m15.4 5.2 3.3-.9 3.1 15.2-3.3.9z" /></Svg>
export const IScore = (p: P) => <Svg {...p}><rect x="5" y="3" width="14" height="18" rx="1.5" /><path d="M8 8h8M8 10.5h8M8 13h8M8 16.5h5" /></Svg>
export const IPractice = (p: P) => <Svg {...p}><path d="M7 6H4v12h3M17 6h3v12h-3" /><path d="M10 9.2v5.6l4.6-2.8z" /></Svg>
export const IPlay = (p: P) => <Svg {...p}><path d="M8 5.2v13.6L18.6 12z" fill="currentColor" /></Svg>
export const IStop = (p: P) => <Svg {...p}><rect x="6.5" y="6.5" width="11" height="11" rx="1.2" fill="currentColor" /></Svg>
export const IPause = (p: P) => <Svg {...p}><rect x="6.5" y="5" width="3.6" height="14" rx="0.8" fill="currentColor" /><rect x="13.9" y="5" width="3.6" height="14" rx="0.8" fill="currentColor" /></Svg>
export const IMinus = (p: P) => <Svg {...p}><path d="M5 12h14" /></Svg>
export const IPlus = (p: P) => <Svg {...p}><path d="M12 5v14M5 12h14" /></Svg>
export const IMetronome = (p: P) => <Svg {...p}><path d="M9 3.5h6l3.6 17H5.4z" /><path d="M7 15.5h10M12 15.5l5-9" /></Svg>
export const IParts = (p: P) => <Svg {...p}><path d="M3.5 6h17M3.5 9h17M3.5 15h17M3.5 18h17" /></Svg>
export const IEar = (p: P) => <Svg {...p}><path d="M7.5 10a4.5 4.5 0 0 1 9 0c0 2.6-2.2 3.4-2.7 5.4-.5 2-1.3 4.1-3.8 4.1-1.6 0-2.7-1-3-2.4" /><path d="M10 10.2a2 2 0 0 1 4 0c0 1.2-1 1.6-1.4 2.4" /></Svg>
export const IHistory = (p: P) => <Svg {...p}><path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3" /><path d="M4 4.5v3.4h3.4" /><path d="M12 8v4.2l2.8 1.8" /></Svg>
export const IClose = (p: P) => <Svg {...p}><path d="M6 6l12 12M18 6 6 18" /></Svg>
export const IChevronLeft = (p: P) => <Svg {...p}><path d="M14.5 5.5 8 12l6.5 6.5" /></Svg>
export const IChevronRight = (p: P) => <Svg {...p}><path d="M9.5 5.5 16 12l-6.5 6.5" /></Svg>
export const IWarning = (p: P) => <Svg {...p}><path d="M12 4 21 19.5H3z" /><path d="M12 10v4.2" /><circle cx="12" cy="16.9" r="0.4" fill="currentColor" /></Svg>
export const ICamera = (p: P) => <Svg {...p}><path d="M4 8h3l1.6-2.5h6.8L17 8h3v11H4z" /><circle cx="12" cy="13.2" r="3.3" /></Svg>
export const ITrash = (p: P) => <Svg {...p}><path d="M5 7h14M10 7V4.8h4V7M7 7l1 13h8l1-13" /></Svg>
export const IMic = (p: P) => <Svg {...p}><rect x="9" y="3.5" width="6" height="11" rx="3" /><path d="M6 11.5a6 6 0 0 0 12 0M12 17.5V21" /></Svg>
export const IScissors = (p: P) => <Svg {...p}><circle cx="6.5" cy="17.5" r="2.5" /><circle cx="17.5" cy="17.5" r="2.5" /><path d="M8.3 15.7 18 4M15.7 15.7 6 4" /></Svg>
export const IPencil = (p: P) => <Svg {...p}><path d="M5 19l1-4L16 5l3 3L9 18z" /><path d="m14 7 3 3" /></Svg>
export const ICheck = (p: P) => <Svg {...p}><path d="m5 12.5 4.5 4.5L19 7" /></Svg>
export const ILock = (p: P) => <Svg {...p}><rect x="5" y="11" width="14" height="9" rx="1.5" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></Svg>
export const IUndo = (p: P) => <Svg {...p}><path d="M9 6.5 5 10.5l4 4" /><path d="M5 10.5h9.5a4.5 4.5 0 0 1 0 9H12" /></Svg>
export const IList = (p: P) => <Svg {...p}><path d="M9 6.5h11M9 12h11M9 17.5h11" /><path d="M4.5 6.5h.01M4.5 12h.01M4.5 17.5h.01" strokeWidth={2.6} /></Svg>
export const IRepeat = (p: P) => <Svg {...p}><path d="m17 3 3 3-3 3" /><path d="M4 11V9.5A3.5 3.5 0 0 1 7.5 6H20" /><path d="m7 21-3-3 3-3" /><path d="M20 13v1.5a3.5 3.5 0 0 1-3.5 3.5H4" /></Svg>
export const IPagePlus = (p: P) => <Svg {...p}><path d="M14 3H6.5v18h11V6.5z" /><path d="M14 3v3.5h3.5M12 10.5v6M9 13.5h6" /></Svg>
export const IGrip = (p: P) => (
  <Svg {...p} stroke="none">
    {[8, 12, 16].map(y => [9.5, 14.5].map(x => <circle key={`${x}-${y}`} cx={x} cy={y} r="1.3" fill="currentColor" />))}
  </Svg>
)
export const IDisplay = (p: P) => <Svg {...p}><circle cx="12" cy="12" r="8.5" /><path d="M12 3.5v17" /><path d="M12 8.5a3.5 3.5 0 0 1 0 7" fill="currentColor" stroke="none" /></Svg>
export const IInfo = (p: P) => <Svg {...p}><circle cx="12" cy="12" r="8.5" /><path d="M12 11v5.2" /><circle cx="12" cy="7.9" r="0.45" fill="currentColor" /></Svg>
export const IExport = (p: P) => <Svg {...p}><path d="M12 14.5v-11" /><path d="m8 7.5 4-4 4 4" /><path d="M4.5 15.5v3.5a1.5 1.5 0 0 0 1.5 1.5h12a1.5 1.5 0 0 0 1.5-1.5v-3.5" /></Svg>
export const IImport = (p: P) => <Svg {...p}><path d="M12 3.5v11" /><path d="m8 10.5 4 4 4-4" /><path d="M4.5 15.5v3.5a1.5 1.5 0 0 0 1.5 1.5h12a1.5 1.5 0 0 0 1.5-1.5v-3.5" /></Svg>
export const IPeople = (p: P) => <Svg {...p}><circle cx="9" cy="8.5" r="3.2" /><path d="M3.5 19.5c.4-3.2 2.6-5.2 5.5-5.2s5.1 2 5.5 5.2" /><path d="M15.2 5.6a3 3 0 0 1 0 5.8M17.4 14.6c1.7.6 2.8 2.3 3.1 4.9" /></Svg>
export const IMore = (p: P) => (
  <Svg {...p} stroke="none">
    {[6, 12, 18].map(x => <circle key={x} cx={x} cy="12" r="1.6" fill="currentColor" />)}
  </Svg>
)
export const IBook = (p: P) => <Svg {...p}><path d="M5 4.5h10.5a2 2 0 0 1 2 2v13H7a2 2 0 0 1-2-2z" /><path d="M5 17.5a2 2 0 0 1 2-2h10.5" /></Svg>
/** A notehead on a staff: the Digital form of a book (engraved from notation). */
export const INote = (p: P) => <Svg {...p}><path d="M3.5 7h17M3.5 10.5h17M3.5 14h17" strokeWidth={1.2} /><ellipse cx="10" cy="17" rx="2.6" ry="1.9" transform="rotate(-20 10 17)" fill="currentColor" /><path d="M12.4 16.2V4.5" /></Svg>
/** A keypad: joining with a code. */
export const IKeypad = (p: P) => (
  <Svg {...p} stroke="none">
    {[6.5, 12, 17.5].map(y => [6.5, 12, 17.5].map(x => <circle key={`${x}-${y}`} cx={x} cy={y} r="1.7" fill="currentColor" />))}
  </Svg>
)
export const IPlusCircle = (p: P) => <Svg {...p}><circle cx="12" cy="12" r="8.5" /><path d="M12 8v8M8 12h8" /></Svg>
