export function Panel({
  title, action, children, bodyClassName = "",
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  bodyClassName?: string;
}) {
  return (
    <section className="rounded-[14px] border border-line bg-surface shadow-panel">
      <div className="flex items-center gap-3 px-5 pb-[13px] pt-[17px]">
        <h3 className="m-0 text-[15px] font-semibold">{title}</h3>
        {action && <div className="ml-auto flex items-center gap-[7px]">{action}</div>}
      </div>
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}
