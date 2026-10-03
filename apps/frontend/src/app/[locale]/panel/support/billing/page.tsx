import { notFound } from "next/navigation";

/**
 * A tool of the platform team, not of a company (answer 42a, UX-056): a
 * company's panel answers 404. The panel component stays in its module for
 * the operator's panel (development-15, „Platforma”).
 */
export default function SupportToolPage(): never {
  notFound();
}
