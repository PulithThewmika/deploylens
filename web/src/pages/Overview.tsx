import { Link } from 'react-router-dom'
import { ServiceCard } from '../components/ServiceCard'
import { ServiceCardSkeleton } from '../components/ServiceCardSkeleton'
import { useServices } from '../hooks/useServices'

export function Overview() {
  const { data: services, isLoading, isError } = useServices()

  return (
    <div className="p-6">
      <h1 className="mb-4 font-heading text-xl font-semibold text-text">Overview</h1>
      {isError ? (
        <p className="text-sm text-failed">Failed to load services. Retrying automatically.</p>
      ) : !isLoading && services?.length === 0 ? (
        <p className="text-sm text-text-muted">
          No services registered yet. Services appear here once a deployment webhook fires.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {isLoading
            ? Array.from({ length: 6 }, (_, i) => <ServiceCardSkeleton key={i} />)
            : services?.map((service) => (
                <Link key={service.id} to={`/services/${service.name}`} className="block">
                  <ServiceCard service={service} />
                </Link>
              ))}
        </div>
      )}
    </div>
  )
}
