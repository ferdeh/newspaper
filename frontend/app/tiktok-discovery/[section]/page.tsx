import { notFound } from "next/navigation";
import TikTokDiscoveryConsole, { type TikTokDiscoverySection } from "@/components/TikTokDiscoveryConsole";

const sections: TikTokDiscoverySection[] = ["overview", "keywords", "manual-search", "videos", "runs", "settings"];

export default async function TikTokDiscoverySectionPage({ params }: { params: Promise<{ section: string }> }) {
  const { section } = await params;
  if (!sections.includes(section as TikTokDiscoverySection)) notFound();
  return <TikTokDiscoveryConsole section={section as TikTokDiscoverySection} />;
}
