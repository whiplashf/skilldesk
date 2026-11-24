import type { ReactNode } from 'react';
import type { Tone } from '../lib/labels';

export interface BadgeProps {
  children: ReactNode;
  tone?: Tone;
  mono?: boolean;
  title?: string;
}

export function Badge({ children, tone = 'neutral', mono = false, title }: BadgeProps) {
  return (
    <span className={`badge badge--${tone}${mono ? ' badge--mono' : ''}`} title={title}>
      {children}
    </span>
  );
}
