import { useState, useEffect, useCallback } from "react";

/**
 * Generic hook for fetching data from an API with automatic re-fetch
 * on dependency changes. Handles loading, error, and refetch states.
 *
 * Usage:
 *   const { data, loading, error, refetch } = useApiData(
 *     () => listConnectors(pluginId),
 *     [pluginId],
 *   );
 */
export function useApiData<T>(
  fetcher: () => Promise<T>,
  deps: React.DependencyList,
  options?: { skip?: boolean }
): {
  data: T | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
  setData: React.Dispatch<React.SetStateAction<T | null>>;
} {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const stableFetcher = useCallback(fetcher, deps);

  const run = useCallback(async () => {
    if (options?.skip) return;
    setLoading(true);
    setError(null);
    try {
      const result = await stableFetcher();
      setData(result);
    } catch (err: any) {
      setError(err?.message || "Request failed");
    } finally {
      setLoading(false);
    }
  }, [stableFetcher, options?.skip]);

  useEffect(() => {
    run();
  }, [run]);

  return { data, loading, error, refetch: run, setData };
}
