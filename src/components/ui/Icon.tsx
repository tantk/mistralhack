interface IconProps {
  name: string
  className?: string
  size?: number
}

export default function Icon({ name, className = '', size = 24 }: IconProps) {
  return (
    <span
      className={`material-symbols-outlined ${className}`}
      style={{ fontSize: size, lineHeight: 1 }}
    >
      {name}
    </span>
  )
}
