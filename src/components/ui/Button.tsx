import { motion } from 'framer-motion'
import type { ComponentPropsWithoutRef } from 'react'

type Variant = 'primary' | 'secondary' | 'destructive' | 'ghost'

interface ButtonProps extends ComponentPropsWithoutRef<typeof motion.button> {
  variant?: Variant
}

const VARIANTS: Record<Variant, string> = {
  primary:
    'border border-neon-cyan text-neon-cyan hover:bg-neon-cyan/10 hover:shadow-glow-cyan font-hud font-semibold uppercase tracking-wider',
  secondary:
    'border border-glass-border text-zinc-300 hover:border-neon-cyan/40 hover:text-neon-cyan font-hud font-semibold uppercase tracking-wider',
  destructive:
    'border border-neon-magenta text-neon-magenta hover:bg-neon-magenta/10 hover:shadow-glow-magenta font-hud font-semibold uppercase tracking-wider',
  ghost:
    'border border-transparent text-zinc-500 hover:text-zinc-300 hover:border-glass-border font-hud font-semibold uppercase tracking-wider',
}

export default function Button({ variant = 'primary', className = '', ...props }: ButtonProps) {
  return (
    <motion.button
      className={`px-5 py-2.5 rounded text-sm transition-all duration-200 cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed ${VARIANTS[variant]} ${className}`}
      whileHover={{ scale: props.disabled ? 1 : 1.02 }}
      whileTap={{ scale: props.disabled ? 1 : 0.98 }}
      {...props}
    />
  )
}
