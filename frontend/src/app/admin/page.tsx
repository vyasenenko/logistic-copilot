import { AdminConsole } from "@/components/AdminConsole";
import { AuthGate } from "@/components/AuthGate";

export default function AdminPage() {
  return (
    <AuthGate>
      <AdminConsole />
    </AuthGate>
  );
}
