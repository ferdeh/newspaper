import { notFound, permanentRedirect } from "next/navigation";
import IntelligenceSection from "@/components/IntelligenceSection";

const sections = ["situation-map", "product-intelligence", "event-intelligence", "hsse", "alerts"];
const situationTabs = ["situation-map", "geographic-intelligence", "tbbm-exposure"];

export default async function SectionPage({
  params,
  searchParams,
}: {
  params: Promise<{ section: string }>;
  searchParams: Promise<{ tab?: string | string[] }>;
}) {
  const { section } = await params;

  if (section === "geographic-intelligence" || section === "tbbm-exposure") {
    permanentRedirect(`/situation-map?tab=${section}`);
  }
  if (section === "tiktok-early-warning") {
    permanentRedirect("/tiktok-discovery/early-warning");
  }
  if (!sections.includes(section)) notFound();

  const requestedTab = (await searchParams).tab;
  const initialTab = typeof requestedTab === "string" && situationTabs.includes(requestedTab)
    ? requestedTab
    : undefined;

  return <IntelligenceSection section={section} initialTab={initialTab} />;
}
