import type { ReactNode } from 'react'

interface GlassCardProps {
  children: ReactNode
  className?: string
  glow?: 'cyan' | 'magenta' | 'yellow'
  borderAccent?: 'cyan' | 'magenta' | 'yellow'
}

const GLOW = {
  cyan: 'shadow-glow-cyan',
  magenta: 'shadow-glow-magenta',
  yellow: 'shadow-glow-yellow',
} as const

const BORDER = {
  cyan: 'border-l-2 border-l-neon-cyan',
  magenta: 'border-l-2 border-l-neon-magenta',
  yellow: 'border-l-2 border-l-neon-yellow',
} as const

export default function GlassCard({ children, className = '', glow, borderAccent }: GlassCardProps) {
  return (
    <div
      className={`glass-panel ${glow ? GLOW[glow] : ''} ${borderAccent ? BORDER[borderAccent] : ''} ${className}`}
    >
      {children}
    </div>
  )
}
