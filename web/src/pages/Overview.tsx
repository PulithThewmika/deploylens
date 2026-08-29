import { useNavigate } from 'react-router-dom'
import { ServiceCard } from '../components/ServiceCard'
import { useServices } from '../hooks/useServices'

export function Overview() {
  const navigate = useNavigate()
  const { data: services } = useServices()

  return (
    <div className="p-6">
      <h1 className="mb-4 font-heading text-xl font-semibold text-text">Overview</h1>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {services?.map((service) => (
          <button
            key={service.id}
            type="button"
            onClick={() => navigate(`/services/${service.name}`)}
            className="w-full text-left"
          >
            <ServiceCard service={service} />
          </button>
        ))}
      </div>
    </div>
  )
}
