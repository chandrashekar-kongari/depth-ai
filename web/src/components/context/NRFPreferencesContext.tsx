"use client";

import React, { createContext, useContext, useState } from "react";
import { LocalStorageKeys } from "@/lib/extension/constants";

interface NRFPreferencesContextValue {
  useDepthAsNewTab: boolean;
  setUseDepthAsNewTab: (v: boolean) => void;
}

const NRFPreferencesContext = createContext<
  NRFPreferencesContextValue | undefined
>(undefined);

function useLocalStorageState<T>(
  key: string,
  defaultValue: T
): [T, (value: T) => void] {
  const [state, setState] = useState<T>(() => {
    if (typeof window !== "undefined") {
      const storedValue = localStorage.getItem(key);
      return storedValue ? JSON.parse(storedValue) : defaultValue;
    }
    return defaultValue;
  });

  const setValue = (value: T) => {
    setState(value);
    if (typeof window !== "undefined") {
      localStorage.setItem(key, JSON.stringify(value));
    }
  };

  return [state, setValue];
}

export function NRFPreferencesProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [useDepthAsNewTab, setUseDepthAsNewTab] = useLocalStorageState<boolean>(
    LocalStorageKeys.USE_ONYX_AS_NEW_TAB,
    true
  );

  return (
    <NRFPreferencesContext.Provider
      value={{
        useDepthAsNewTab,
        setUseDepthAsNewTab,
      }}
    >
      {children}
    </NRFPreferencesContext.Provider>
  );
}

export function useNRFPreferences() {
  const context = useContext(NRFPreferencesContext);
  if (!context) {
    throw new Error(
      "useNRFPreferences must be used within an NRFPreferencesProvider"
    );
  }
  return context;
}
