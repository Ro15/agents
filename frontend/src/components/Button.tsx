import React from "react";
import classNames from "../utils/classNames";

type ButtonElement = "button" | "a";
type ButtonVariant = "primary" | "secondary" | "ghost";
type ButtonSize = "md" | "sm";

type BaseProps = {
  variant?: ButtonVariant;
  size?: ButtonSize;
  as?: ButtonElement;
  className?: string;
  children: React.ReactNode;
};

type AnchorButtonProps = BaseProps & React.AnchorHTMLAttributes<HTMLAnchorElement> & { as: "a" };
type NativeButtonProps = BaseProps & React.ButtonHTMLAttributes<HTMLButtonElement> & { as?: "button" };

type ButtonProps = AnchorButtonProps | NativeButtonProps;

export const Button: React.FC<ButtonProps> = (props) => {
  const { variant = "primary", size = "md", as = "button", className, children, ...rest } = props as any;
  const base =
    "inline-flex items-center justify-center rounded-md font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2";
  const sizeStyles: Record<string, string> = {
    md: "px-3 py-2 text-sm",
    sm: "px-2.5 py-1.5 text-xs",
  };
  const styles: Record<string, string> = {
    primary: "bg-brand-blue text-white hover:bg-brand-blue/90 focus:ring-brand-blue",
    secondary: "bg-white text-brand-blue border border-brand-blue hover:bg-brand-blue/5 focus:ring-brand-blue",
    ghost: "bg-transparent text-slate-700 hover:bg-slate-100 focus:ring-slate-300",
  };
  const Component = as as any;
  return (
    <Component className={classNames(base, sizeStyles[size], styles[variant], className)} {...rest}>
      {children}
    </Component>
  );
};
