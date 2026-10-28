import type { ReactNode, SVGProps } from 'react'

/** Icons for marking and scribbling, in the app's stroke (icons.tsx): 24 grid, 1.75, round. */
type P = Omit<SVGProps<SVGSVGElement>, 'children'> & { size?: number }
function Svg({ size = 24, children, ...rest }: P & { children: ReactNode }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" {...rest}>
      {children}
    </svg>
  )
}
/** A highlighter: chisel tip over a wash. */
export const IHighlight = ({ on, ...p }: P & { on?: boolean }) => (
  <Svg {...p}>
    <rect x="3" y="17.5" width="18" height="4" rx="1" className="i-wash" fill={on ? 'currentColor' : 'none'} stroke="none" />
    <path d="M9.2 14.8 6.5 17.5h3.2l1.6-1.6" /><path d="m9.2 14.8 7.6-9.9a1.6 1.6 0 0 1 2.4-.1l.4.4a1.6 1.6 0 0 1-.1 2.4l-9.9 7.6z" /><path d="m11.3 16.9-2.1-2.1" />
  </Svg>
)
export const INote = (p: P) => <Svg {...p}><path d="M5 5.5h14v9.5l-4 4H5z" /><path d="M15 19v-4h4" /><path d="M8.5 9.5h7M8.5 12.5h4" /></Svg>
export const IScribble = (p: P) => <Svg {...p}><path d="M3.5 15.5c2.2-4.8 4.3-7.4 5.6-6.5 1.6 1.1-2.4 6.6-.6 7.4 1.7.8 4.2-6.9 6.3-6.2 1.8.6-.8 5 .9 5.6 1.2.4 2.6-1.3 4.8-3.6" /></Svg>
export const IPen = (p: P) => <Svg {...p}><path d="M14.5 5.5 18.5 9.5 9 19H5v-4z" /><path d="m12.5 7.5 4 4" /></Svg>
export const IEraser = (p: P) => <Svg {...p}><path d="m8.6 19.5-4.1-4.1a1.6 1.6 0 0 1 0-2.3l8.6-8.6a1.6 1.6 0 0 1 2.3 0l4.1 4.1a1.6 1.6 0 0 1 0 2.3l-8.6 8.6z" /><path d="m9.8 7.8 6.4 6.4" /><path d="M8.6 19.5H20" /></Svg>
