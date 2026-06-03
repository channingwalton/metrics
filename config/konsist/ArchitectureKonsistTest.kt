// Example Konsist architecture tests (Kotlin-native).
// Konsist scans Kotlin *source* and runs as normal tests, so it lives in your
// build rather than being run standalone by analyse.sh.
//
// Dependency: com.lemonappdev:konsist
// Docs: https://docs.konsist.lemonappdev.com
//
// A balanced starting set: layering, no domain->infra imports, naming, and a
// couple of hygiene checks. Adapt the package roots to your project.
package architecture

import com.lemonappdev.konsist.api.Konsist
import com.lemonappdev.konsist.api.architecture.KoArchitectureCreator.assertArchitecture
import com.lemonappdev.konsist.api.architecture.Layer
import com.lemonappdev.konsist.api.verify.assertFalse
import com.lemonappdev.konsist.api.verify.assertTrue
import org.junit.jupiter.api.Test

class ArchitectureKonsistTest {

    private val domain = Layer("Domain", "com.example.domain..")
    private val application = Layer("Application", "com.example.application..")
    private val infrastructure = Layer("Infrastructure", "com.example.infrastructure..")

    @Test
    fun `layers respect dependency direction`() {
        Konsist.scopeFromProject().assertArchitecture {
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

    @Test
    fun `domain is free of framework imports`() {
        Konsist.scopeFromProject()
            .files
            .filter { it.packagee?.name?.startsWith("com.example.domain") == true }
            .assertFalse { file ->
                file.imports.any { it.name.startsWith("org.springframework") }
            }
    }

    @Test
    fun `repository interfaces are named correctly`() {
        Konsist.scopeFromProject()
            .interfaces()
            .filter { it.resideInPackage("..repository..") }
            .assertTrue { it.hasNameEndingWith("Repository") }
    }

    @Test
    fun `no field is mutable in domain data classes`() {
        Konsist.scopeFromProject()
            .classes()
            .filter { it.resideInPackage("..domain..") && it.hasModifier(com.lemonappdev.konsist.api.KoModifier.DATA) }
            .properties()
            .assertFalse { it.hasVarModifier }
    }
}
