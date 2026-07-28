import { useEffect } from "react";

interface Props {
  message: string;
  onDismiss: () => void;
}

export function Toast({ message, onDismiss }: Props) {
  useEffect(() => {
    const t = setTimeout(onDismiss, 3500);
    return () => clearTimeout(t);
  }, [message, onDismiss]);

  return (
    <div className="toast" role="status">
      {message}
    </div>
  );
}
