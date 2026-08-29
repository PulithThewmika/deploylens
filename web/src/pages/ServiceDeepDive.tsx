import { useParams } from 'react-router-dom'

export function ServiceDeepDive() {
  const { name } = useParams<{ name: string }>()

  return (
    <div className="p-6">
      <h1 className="font-heading text-xl font-semibold text-text">{name}</h1>
    </div>
  )
}
