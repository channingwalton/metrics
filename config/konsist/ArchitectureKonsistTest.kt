// Example Konsist architecture test (Kotlin-native).
// Konsist scans Kotlin *source* and runs as a normal test, so it lives in your
// build rather than being run standalone by analyse.sh.
//
// Dependency: com.lemonappdev:konsist
// Docs: https://docs.konsist.lemonappdev.com
package architecture

import com.lemonappdev.konsist.api.Konsist
import com.lemonappdev.konsist.api.architecture.KoArchitectureCreator.assertArchitecture
import com.lemonappdev.konsist.api.architecture.Layer
import org.junit.jupiter.api.Test

class ArchitectureKonsistTest {

    private val domain = Layer("Domain", "com.example.domain..")
    private val application = Layer("Application", "com.example.application..")
    private val infrastructure = Layer("Infrastructure", "com.example.infrastructure..")

    @Test
    fun `layers respect dependency direction`() {
        Konsist.scopeFromProject().assertArchitecture {
            // Fowler-style dependency rules.
            domain.dependsOnNothing()
            application.dependsOn(domain)
            infrastructure.dependsOn(application, domain)
        }
    }

    @Test
    fun `no class in domain imports infrastructure`() {
        Konsist.scopeFromProject()
            .files
            .filter { it.packagee?.name?.startsWith("com.example.domain") == true }
            .assertFalse { file ->
                file.imports.any { it.name.contains("infrastructure") }
            }
    }
}
