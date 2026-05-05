import { AuthGate } from "@/components/AuthGate";
import { FreightDashboard } from "@/components/FreightDashboard";

export default function DashboardPage() {
  return (
    <AuthGate>
      <FreightDashboard />
    </AuthGate>
  );
}
