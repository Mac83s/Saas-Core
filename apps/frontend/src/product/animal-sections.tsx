import type { ProductAnimalSection } from "#lib/product-extension";

/**
 * The product slot for the animal card (ADR-049, ADR-051). Saas-Core has no
 * section of its own, so the card shows what the register knows — ear tag,
 * name, farm, status, dates. A product repository replaces this file with its
 * own sections (HoofCare's limb diagram, trimming timeline and next check-up),
 * and each section's `module`/`organizationTypes`/`permission` say for whom.
 */
const animalSections: ProductAnimalSection[] = [];

export default animalSections;
