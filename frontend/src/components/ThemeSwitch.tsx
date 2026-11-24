import type { ThemePref } from '../lib/theme';

export interface ThemeSwitchProps {
  pref: ThemePref;
  onChange: (pref: ThemePref) => void;
}

const OPTIONS: ReadonlyArray<{ value: ThemePref; label: string; title: string }> = [
  { value: 'light', label: '浅', title: '浅色' },
  { value: 'dark', label: '深', title: '深色' },
  { value: 'system', label: '自动', title: '跟随系统' },
];

export function ThemeSwitch({ pref, onChange }: ThemeSwitchProps) {
  return (
    <div className="theme-switch" role="group" aria-label="主题">
      {OPTIONS.map((option) => {
        const active = option.value === pref;
        return (
          <button
            key={option.value}
            type="button"
            className={active ? 'is-active' : undefined}
            aria-pressed={active}
            title={option.title}
            onClick={() => {
              onChange(option.value);
            }}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
