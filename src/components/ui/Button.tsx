import { motion } from 'framer-motion'
import type { ComponentPropsWithoutRef } from 'react'

type Variant = 'primary' | 'secondary' | 'destructive' | 'ghost'

interface ButtonProps extends ComponentPropsWithoutRef<typeof motion.button> {
  variant?: Variant
}

const VARIANTS: Record<Variant, string> = {
  primary:
    'border border-accent text-accent hover:bg-accent/10 hover:shadow-glow-cyan font-display font-semibold uppercase tracking-wider',
  secondary:
    'border border-accent/20 text-slate-300 hover:border-accent/40 hover:text-accent font-display font-semibold uppercase tracking-wider',
  destructive:
    'border border-danger text-danger hover:bg-danger/10 hover:shadow-glow-magenta font-display font-semibold uppercase tracking-wider',
  ghost:
    'border border-transparent text-slate-500 hover:text-slate-300 hover:border-accent/10 font-display font-semibold uppercase tracking-wider',
}

export default function Button({ variant = 'primary', className = '', ...props }: ButtonProps) {
  return (
    <motion.button
      className={`px-5 py-2.5 rounded-lg text-sm transition-all duration-200 cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed ${VARIANTS[variant]} ${className}`}
      whileHover={{ scale: props.disabled ? 1 : 1.02 }}
      whileTap={{ scale: props.disabled ? 1 : 0.98 }}
      {...props}
    />
  )
}
