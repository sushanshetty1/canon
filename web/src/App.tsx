import { Closing } from './sections/Closing'
import { Company } from './sections/Company'
import { Hero } from './sections/Hero'
import { HowItChecks } from './sections/HowItChecks'
import { Product } from './sections/Product'
import { Sources } from './sections/Sources'

export function App() {
  return (
    <main className="min-h-[100dvh] space-y-3 p-3 sm:space-y-4 sm:p-4">
      <Hero />
      <Sources />
      <HowItChecks />
      <Product />
      <Company />
      <Closing />
    </main>
  )
}
