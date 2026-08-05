/**
 * useLocalStorage.ts — Generic hook for persisting state to localStorage.
 */

import { useState, useEffect, useCallback } from "react";

export function useLocalStorage<T>(
  key: string,
  initialValue: T,
): [T, (value: T | ((prev: T) => T)) => void] {
  const [storedValue, setStoredValue] = useState<T>(() => {
    try {
      const item = window.localStorage.getItem(key);
      return item != null ? (JSON.parse(item) as T) : initialValue;
    } catch {
      return initialValue;
    }
  });

  const setValue = useCallback(
    (value: T | ((prev: T) => T)) => {
      try {
        const toStore =
          typeof value === "function"
            ? (value as (prev: T) => T)(storedValue)
            : value;
        setStoredValue(toStore);
        window.localStorage.setItem(key, JSON.stringify(toStore));
      } catch (err) {
        console.warn("[useLocalStorage] Could not save:", key, err);
      }
    },
    [key, storedValue],
  );

  useEffect(() => {
    const handler = (e: StorageEvent) => {
      if (e.key === key && e.newValue !== null) {
        try {
          setStoredValue(JSON.parse(e.newValue) as T);
        } catch {
          // ignore
        }
      }
    };
    window.addEventListener("storage", handler);
    return () => window.removeEventListener("storage", handler);
  }, [key]);

  return [storedValue, setValue];
}

export default useLocalStorage;
