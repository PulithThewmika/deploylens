import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'

const queryClient = new QueryClient()

function PlaceholderPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background text-text">
      <h1 className="font-heading text-2xl">DeployLens</h1>
    </main>
  )
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<PlaceholderPage />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
