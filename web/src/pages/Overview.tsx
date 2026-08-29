import { useNavigate } from 'react-router-dom'
import { ServiceCard } from '../components/ServiceCard'
import { ServiceCardSkeleton } from '../components/ServiceCardSkeleton'
import { useServices } from '../hooks/useServices'

export function Overview() {
  const navigate = useNavigate()
  const { data: services, isLoading } = useServices()

  return (
    <div className="p-6">
      <h1 className="mb-4 font-heading text-xl font-semibold text-text">Overview</h1>
      {!isLoading && services?.length === 0 ? (
        <p className="text-sm text-text-muted">
          No services registered yet. Services appear here once a deployment webhook fires.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {isLoading
            ? Array.from({ length: 6 }, (_, i) => <ServiceCardSkeleton key={i} />)
            : services?.map((service) => (
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
      )}
    </div>
  )
}
