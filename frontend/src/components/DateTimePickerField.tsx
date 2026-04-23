"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Calendar, ChevronLeft, ChevronRight, Clock3, X } from "lucide-react";

interface DateTimePickerFieldProps {
  label?: string;
  value: string;
  placeholder?: string;
  onChange: (value: string) => void;
  autoOpenSignal?: number;
}

const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH_LABELS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const HOUR_OPTIONS = Array.from({ length: 12 }, (_, index) => String(index + 1));
const MINUTE_OPTIONS = Array.from({ length: 12 }, (_, index) => String(index * 5).padStart(2, "0"));
const PERIOD_OPTIONS = ["AM", "PM"] as const;

function parseLocalValue(value: string): Date | null {
  if (!value) return null;
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/);
  if (!match) return null;
  const [, year, month, day, hour, minute] = match;
  const parsed = new Date(
    Number(year),
    Number(month) - 1,
    Number(day),
    Number(hour),
    Number(minute),
    0,
    0,
  );
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function toLocalInputValue(date: Date | null) {
  if (!date) return "";
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatTriggerLabel(value: string, placeholder: string) {
  const parsed = parseLocalValue(value);
  if (!parsed) return placeholder;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(parsed);
}

function buildCalendarDays(monthDate: Date) {
  const year = monthDate.getFullYear();
  const month = monthDate.getMonth();
  const firstDay = new Date(year, month, 1);
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const startOffset = firstDay.getDay();
  const days = [];

  for (let index = 0; index < startOffset; index += 1) {
    days.push(null);
  }
  for (let day = 1; day <= daysInMonth; day += 1) {
    days.push(new Date(year, month, day));
  }
  while (days.length % 7 !== 0) {
    days.push(null);
  }
  return days;
}

function getTimePartsForPicker(date: Date | null) {
  const hours24 = date ? date.getHours() : 8;
  const hour12 = ((hours24 + 11) % 12) + 1;
  const period = hours24 >= 12 ? "PM" : "AM";
  return {
    hour12: String(hour12),
    minute: date ? String(date.getMinutes()).padStart(2, "0") : "00",
    period: period as (typeof PERIOD_OPTIONS)[number],
  };
}

export function DateTimePickerField({
  label,
  value,
  placeholder = "Pick date and time",
  onChange,
  autoOpenSignal = 0,
}: DateTimePickerFieldProps) {
  const POPUP_WIDTH = 356;
  const DESKTOP_POPUP_HEIGHT = 404;
  const VIEWPORT_GAP = 16;
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const popupRef = useRef<HTMLDivElement | null>(null);
  const previousAutoOpenSignal = useRef(autoOpenSignal);
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number; width: number; maxHeight: number; placement: "bottom" | "top" }>({
    top: 0,
    left: 0,
    width: POPUP_WIDTH,
    maxHeight: DESKTOP_POPUP_HEIGHT,
    placement: "bottom",
  });
  const selectedDate = useMemo(() => parseLocalValue(value), [value]);
  const [viewMonth, setViewMonth] = useState<Date>(() => selectedDate ? new Date(selectedDate.getFullYear(), selectedDate.getMonth(), 1) : new Date(new Date().getFullYear(), new Date().getMonth(), 1));

  const updatePopupPosition = useCallback(() => {
    if (!triggerRef.current) return;
    const rect = triggerRef.current.getBoundingClientRect();
    const viewportHeight = window.innerHeight;
    const viewportWidth = window.innerWidth;
    const popupWidth = Math.min(
      Math.max(rect.width, POPUP_WIDTH),
      Math.max(300, viewportWidth - VIEWPORT_GAP * 2),
    );
    const unclampedLeft = rect.left;
    const maxLeft = viewportWidth - popupWidth - VIEWPORT_GAP;
    const left = Math.max(VIEWPORT_GAP, Math.min(unclampedLeft, maxLeft));
    const spaceBelow = viewportHeight - rect.bottom - VIEWPORT_GAP;
    const spaceAbove = rect.top - VIEWPORT_GAP;
    const preferredPlacement: "bottom" | "top" = spaceBelow >= 300 || spaceBelow >= spaceAbove ? "bottom" : "top";
    const availableByPlacement = preferredPlacement === "top" ? spaceAbove : spaceBelow;
    const maxHeight = Math.max(220, Math.min(DESKTOP_POPUP_HEIGHT, availableByPlacement));
    const unclampedTop = preferredPlacement === "top"
      ? rect.top - maxHeight - 10
      : rect.bottom + 10;
    const maxTop = viewportHeight - maxHeight - VIEWPORT_GAP;
    const top = Math.max(VIEWPORT_GAP, Math.min(unclampedTop, maxTop));

    setPosition({
      top,
      left,
      width: popupWidth,
      maxHeight,
      placement: preferredPlacement,
    });
  }, [DESKTOP_POPUP_HEIGHT, POPUP_WIDTH, VIEWPORT_GAP]);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!selectedDate) return;
    setViewMonth(new Date(selectedDate.getFullYear(), selectedDate.getMonth(), 1));
  }, [selectedDate]);

  useEffect(() => {
    if (!mounted) return;
    const changed = autoOpenSignal > 0 && autoOpenSignal !== previousAutoOpenSignal.current;
    previousAutoOpenSignal.current = autoOpenSignal;
    if (!changed) return;
    setOpen(true);
    requestAnimationFrame(() => {
      triggerRef.current?.focus();
    });
  }, [autoOpenSignal, mounted]);

  useEffect(() => {
    if (!open) return;
    updatePopupPosition();
    const frame = requestAnimationFrame(updatePopupPosition);
    const handleViewportChange = () => updatePopupPosition();
    window.addEventListener("resize", handleViewportChange);
    window.addEventListener("scroll", handleViewportChange, true);
    window.visualViewport?.addEventListener("resize", handleViewportChange);
    window.visualViewport?.addEventListener("scroll", handleViewportChange);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", handleViewportChange);
      window.removeEventListener("scroll", handleViewportChange, true);
      window.visualViewport?.removeEventListener("resize", handleViewportChange);
      window.visualViewport?.removeEventListener("scroll", handleViewportChange);
    };
  }, [open, updatePopupPosition]);

  useEffect(() => {
    if (!open) return;
    const handlePointer = (event: MouseEvent) => {
      const target = event.target as Node;
      if (popupRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      setOpen(false);
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("mousedown", handlePointer);
    window.addEventListener("keydown", handleEscape);
    return () => {
      window.removeEventListener("mousedown", handlePointer);
      window.removeEventListener("keydown", handleEscape);
    };
  }, [open]);

  const updateDatePart = (nextDate: Date) => {
    const base = selectedDate ? new Date(selectedDate) : new Date();
    base.setFullYear(nextDate.getFullYear(), nextDate.getMonth(), nextDate.getDate());
    onChange(toLocalInputValue(base));
  };

  const updateTimePart = (kind: "hour12" | "minute" | "period", nextValue: string) => {
    const base = selectedDate ? new Date(selectedDate) : new Date(viewMonth.getFullYear(), viewMonth.getMonth(), 1, 8, 0, 0, 0);
    if (kind === "hour12") {
      const currentPeriod = base.getHours() >= 12 ? "PM" : "AM";
      let nextHour24 = Number(nextValue) % 12;
      if (currentPeriod === "PM") {
        nextHour24 += 12;
      }
      base.setHours(nextHour24);
    }
    if (kind === "minute") base.setMinutes(Number(nextValue));
    if (kind === "period") {
      const currentHours = base.getHours();
      if (nextValue === "PM" && currentHours < 12) {
        base.setHours(currentHours + 12);
      } else if (nextValue === "AM" && currentHours >= 12) {
        base.setHours(currentHours - 12);
      }
    }
    onChange(toLocalInputValue(base));
  };

  const calendarDays = buildCalendarDays(viewMonth);
  const selectedDayKey = selectedDate ? `${selectedDate.getFullYear()}-${selectedDate.getMonth()}-${selectedDate.getDate()}` : null;
  const timeParts = getTimePartsForPicker(selectedDate);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="field-input flex min-h-[46px] w-full items-center justify-between gap-2 text-left"
      >
        <div className="min-w-0">
          {label && <span className="block text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">{label}</span>}
          <span className={`block truncate text-sm ${value ? "text-white" : "text-slate-400"}`}>
            {formatTriggerLabel(value, placeholder)}
          </span>
        </div>
        <Calendar size={18} className="shrink-0 text-cyan-100/80" />
      </button>

      {open && mounted && typeof document !== "undefined"
        ? createPortal(
            <div
              ref={popupRef}
              className="fixed z-[220] overflow-hidden rounded-[24px] border border-cyan-200/16 bg-[#0c1525] shadow-[0_24px_100px_rgba(2,8,23,0.62)]"
              style={{ top: position.top, left: position.left, width: position.width, maxHeight: position.maxHeight }}
            >
              <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(103,232,249,0.08),transparent_36%),linear-gradient(180deg,rgba(255,255,255,0.02),rgba(255,255,255,0))]" />
              <div className="relative space-y-2.5 overflow-y-auto p-3" style={{ maxHeight: position.maxHeight }}>
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-[10px] uppercase tracking-[0.22em] text-cyan-200/55">Pick schedule</p>
                    <p className="mt-1 text-[15px] font-semibold text-white">{formatTriggerLabel(value, placeholder)}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    {value && (
                      <button
                        type="button"
                        onClick={() => onChange("")}
                        className="inline-flex h-8 items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-2.5 text-[11px] uppercase tracking-[0.14em] text-slate-300 transition hover:bg-white/[0.08] hover:text-white"
                      >
                        <X size={14} />
                        Clear
                      </button>
                    )}
                  </div>
                </div>

                <div className="rounded-[20px] border border-white/10 bg-white/[0.03] p-2.5">
                  <div className="mb-2 flex items-center justify-between">
                    <button
                      type="button"
                      onClick={() => setViewMonth((current) => new Date(current.getFullYear(), current.getMonth() - 1, 1))}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-white/10 bg-white/[0.03] text-slate-300 transition hover:bg-white/[0.08] hover:text-white"
                    >
                      <ChevronLeft size={16} />
                    </button>
                    <p className="text-[13px] font-medium text-white">
                      {MONTH_LABELS[viewMonth.getMonth()]} {viewMonth.getFullYear()}
                    </p>
                    <button
                      type="button"
                      onClick={() => setViewMonth((current) => new Date(current.getFullYear(), current.getMonth() + 1, 1))}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-white/10 bg-white/[0.03] text-slate-300 transition hover:bg-white/[0.08] hover:text-white"
                    >
                      <ChevronRight size={16} />
                    </button>
                  </div>

                  <div className="grid grid-cols-7 gap-1">
                    {WEEKDAY_LABELS.map((day) => (
                      <div key={day} className="pb-0.5 text-center text-[9px] uppercase tracking-[0.16em] text-slate-500">
                        {day}
                      </div>
                    ))}
                    {calendarDays.map((day, index) => {
                      if (!day) {
                        return <div key={`empty-${index}`} className="h-8 rounded-xl" />;
                      }
                      const dayKey = `${day.getFullYear()}-${day.getMonth()}-${day.getDate()}`;
                      const isSelected = dayKey === selectedDayKey;
                      return (
                        <button
                          key={dayKey}
                          type="button"
                          onClick={() => updateDatePart(day)}
                          className={`h-8 rounded-xl text-sm transition ${
                            isSelected
                              ? "bg-cyan-200 text-slate-950 shadow-[0_10px_30px_rgba(103,232,249,0.28)]"
                              : "bg-white/[0.03] text-slate-200 hover:bg-white/[0.08] hover:text-white"
                          }`}
                        >
                          {day.getDate()}
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="grid gap-2.5 sm:grid-cols-3">
                  <label className="rounded-[18px] border border-white/10 bg-white/[0.03] p-2.5">
                    <span className="flex items-center gap-2 text-[10px] uppercase tracking-[0.18em] text-slate-400">
                      <Clock3 size={13} />
                      Hour
                    </span>
                    <select
                      value={timeParts.hour12}
                      onChange={(event) => updateTimePart("hour12", event.target.value)}
                      className="mt-1.5 w-full bg-transparent text-sm text-white outline-none"
                    >
                      {HOUR_OPTIONS.map((hour) => (
                        <option key={hour} value={hour} className="bg-slate-900">
                          {hour}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="rounded-[18px] border border-white/10 bg-white/[0.03] p-2.5">
                    <span className="flex items-center gap-2 text-[10px] uppercase tracking-[0.18em] text-slate-400">
                      <Clock3 size={13} />
                      Minute
                    </span>
                    <select
                      value={timeParts.minute}
                      onChange={(event) => updateTimePart("minute", event.target.value)}
                      className="mt-1.5 w-full bg-transparent text-sm text-white outline-none"
                    >
                      {MINUTE_OPTIONS.map((minute) => (
                        <option key={minute} value={minute} className="bg-slate-900">
                          {minute}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="rounded-[18px] border border-white/10 bg-white/[0.03] p-2.5">
                    <span className="flex items-center gap-2 text-[10px] uppercase tracking-[0.18em] text-slate-400">
                      <Clock3 size={13} />
                      AM/PM
                    </span>
                    <select
                      value={timeParts.period}
                      onChange={(event) => updateTimePart("period", event.target.value)}
                      className="mt-1.5 w-full bg-transparent text-sm text-white outline-none"
                    >
                      {PERIOD_OPTIONS.map((period) => (
                        <option key={period} value={period} className="bg-slate-900">
                          {period}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>

                <div className="flex justify-end rounded-[18px] border border-white/10 bg-white/[0.03] px-3 py-2 text-[11px] uppercase tracking-[0.16em] text-slate-400">
                  <button
                    type="button"
                    onClick={() => setOpen(false)}
                    className="rounded-full border border-white/10 px-3 py-1 text-slate-300 transition hover:bg-white/[0.08] hover:text-white"
                  >
                    Done
                  </button>
                </div>
              </div>
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
