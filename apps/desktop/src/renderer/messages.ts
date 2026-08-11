export interface StoredMessage {
  id: string;
  request_id: string;
  user_id: string;
  role: string;
  content: string;
  created_at: string;
}

export const isStoredMessage = (value: unknown): value is StoredMessage => {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate["id"] === "string" &&
    typeof candidate["request_id"] === "string" &&
    typeof candidate["role"] === "string" &&
    typeof candidate["content"] === "string" &&
    typeof candidate["created_at"] === "string"
  );
};

export async function fetchHistory(baseUrl: string): Promise<StoredMessage[]> {
  const response = await fetch(`${baseUrl}/messages`);

  if (!response.ok) {
    throw new Error(`history request failed: ${response.status}`);
  }

  const parsed: unknown = await response.json();

  if (!Array.isArray(parsed)) {
    throw new Error("history response was not an array");
  }

  return parsed.filter(isStoredMessage);
}
