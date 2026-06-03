// Example ArchUnit dependency-rule test (Java/JVM, incl. Kotlin bytecode).
// ArchUnit runs as a normal JUnit test against compiled classes, so it lives in
// your build (Maven/Gradle) rather than being run standalone by analyse.sh.
//
// Dependency: com.tngtech.archunit:archunit-junit5
// Docs: https://www.archunit.org/userguide/html/000_Index.html
package architecture;

import com.tngtech.archunit.core.importer.ImportOption;
import com.tngtech.archunit.junit.AnalyzeClasses;
import com.tngtech.archunit.junit.ArchTest;
import com.tngtech.archunit.lang.ArchRule;

import static com.tngtech.archunit.library.Architectures.layeredArchitecture;
import static com.tngtech.archunit.library.dependencies.SliceRule.*;
import static com.tngtech.archunit.library.dependencies.SlicesRuleDefinition.slices;

@AnalyzeClasses(packages = "com.example", importOptions = ImportOption.DoNotIncludeTests.class)
public class LayeredArchitectureTest {

    @ArchTest
    static final ArchRule layering = layeredArchitecture().consideringAllDependencies()
            .layer("Domain").definedBy("..domain..")
            .layer("Application").definedBy("..application..")
            .layer("Infrastructure").definedBy("..infrastructure..")
            // Dependency rules: who may depend on whom.
            .whereLayer("Infrastructure").mayNotBeAccessedByAnyLayer()
            .whereLayer("Application").mayOnlyBeAccessedByLayers("Infrastructure")
            .whereLayer("Domain").mayOnlyBeAccessedByLayers("Application", "Infrastructure");

    @ArchTest
    static final ArchRule noCycles = slices()
            .matching("com.example.(*)..")
            .should().beFreeOfCycles();
}
