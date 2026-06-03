// Example ArchUnit dependency-rule tests (Java/JVM, incl. Kotlin bytecode).
// ArchUnit runs as normal JUnit tests against compiled classes, so it lives in
// your build (Maven/Gradle) rather than being run standalone by analyse.sh.
//
// Dependency: com.tngtech.archunit:archunit-junit5
// Docs: https://www.archunit.org/userguide/html/000_Index.html
//
// A balanced starting set: layering, no cycles, no cross-package back-references,
// and a few widely-agreed hygiene rules. Adapt the base package and layer
// definitions to your project, then delete rules you don't want.
package architecture;

import com.tngtech.archunit.core.importer.ImportOption;
import com.tngtech.archunit.junit.AnalyzeClasses;
import com.tngtech.archunit.junit.ArchTest;
import com.tngtech.archunit.lang.ArchRule;

import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.classes;
import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noClasses;
import static com.tngtech.archunit.library.Architectures.layeredArchitecture;
import static com.tngtech.archunit.library.GeneralCodingRules.*;
import static com.tngtech.archunit.library.dependencies.SlicesRuleDefinition.slices;

@AnalyzeClasses(packages = "com.example", importOptions = ImportOption.DoNotIncludeTests.class)
public class LayeredArchitectureTest {

    // --- layering: who may depend on whom ----------------------------------
    @ArchTest
    static final ArchRule layering = layeredArchitecture().consideringAllDependencies()
            .layer("Domain").definedBy("..domain..")
            .layer("Application").definedBy("..application..")
            .layer("Infrastructure").definedBy("..infrastructure..")
            .layer("Presentation").definedBy("..web..", "..api..")
            .whereLayer("Presentation").mayNotBeAccessedByAnyLayer()
            .whereLayer("Infrastructure").mayOnlyBeAccessedByLayers("Presentation")
            .whereLayer("Application").mayOnlyBeAccessedByLayers("Presentation", "Infrastructure")
            .whereLayer("Domain").mayOnlyBeAccessedByLayers("Application", "Infrastructure", "Presentation");

    // --- no cycles between top-level slices ---------------------------------
    @ArchTest
    static final ArchRule noCycles = slices()
            .matching("com.example.(*)..")
            .should().beFreeOfCycles();

    // --- domain must stay free of framework leakage -------------------------
    @ArchTest
    static final ArchRule domainHasNoSpringDependencies = noClasses()
            .that().resideInAPackage("..domain..")
            .should().dependOnClassesThat().resideInAnyPackage("org.springframework..")
            .because("the domain model should not depend on the web framework");

    // --- general hygiene (from ArchUnit's built-in library) -----------------
    @ArchTest
    static final ArchRule noFieldInjection = NO_CLASSES_SHOULD_USE_FIELD_INJECTION;

    @ArchTest
    static final ArchRule noJavaUtilLogging = NO_CLASSES_SHOULD_USE_JAVA_UTIL_LOGGING;

    @ArchTest
    static final ArchRule noGenericExceptions = NO_CLASSES_SHOULD_THROW_GENERIC_EXCEPTIONS;

    @ArchTest
    static final ArchRule noStandardStreams = NO_CLASSES_SHOULD_ACCESS_STANDARD_STREAMS;

    // --- naming conventions -------------------------------------------------
    @ArchTest
    static final ArchRule repositoriesNamedProperly = classes()
            .that().resideInAPackage("..repository..")
            .should().haveSimpleNameEndingWith("Repository");
}
