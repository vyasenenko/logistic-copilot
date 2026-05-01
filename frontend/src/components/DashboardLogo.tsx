/** Header mark — uses public/icons/logo.png */
export function DashboardLogo({ className }: { className?: string }) {
  return (
    <img
      src="/icons/logo.png"
      alt=""
      width={24}
      height={24}
      className={className}
      decoding="async"
      draggable={false}
    />
  );
}
