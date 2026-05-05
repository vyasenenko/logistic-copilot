import type { Metadata } from "next";
import { PRODUCT_DISPLAY_NAME } from "@/constants/brand";
import { HeroLogin } from "@/components/HeroLogin";

export const metadata: Metadata = {
  title: "LogistiCopilot | Freight Control Tower",
  description: `${PRODUCT_DISPLAY_NAME} hero page`,
};

export default function Home() {
  return <HeroLogin />;
}
