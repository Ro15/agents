import React from "react";

type Option = { label: string; value: string };

interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  options: Option[];
}

export const Select: React.FC<SelectProps> = ({ label, options, ...rest }) => {
  return (
    <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
      {label && <span>{label}</span>}
      <select
        className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-brand-blue focus:outline-none focus:ring-2 focus:ring-brand-blue/30"
        {...rest}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
};
