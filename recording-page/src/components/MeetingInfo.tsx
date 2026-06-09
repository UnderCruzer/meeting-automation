import { formatTime, formatDuration } from "@/lib/meetingTime";

interface MeetingInfoProps {
  title: string;
  startTime: string;
  endTime: string;
  location: string;
}

export function MeetingInfo({ title, startTime, endTime, location }: MeetingInfoProps) {
  return (
    <div style={styles.card}>
      <h2 style={styles.title}>{title}</h2>
      <div style={styles.row}>
        <span style={styles.label}>시간</span>
        <span>{formatTime(startTime)} ~ {formatTime(endTime)} ({formatDuration(startTime, endTime)})</span>
      </div>
      <div style={styles.row}>
        <span style={styles.label}>장소</span>
        <span>{location || "미지정"}</span>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  card: {
    background: "#f8f9fa",
    borderRadius: 12,
    padding: "20px 24px",
    marginBottom: 24,
    border: "1px solid #e9ecef",
  },
  title: { margin: "0 0 12px", fontSize: 18, fontWeight: 600 },
  row: { display: "flex", gap: 12, marginTop: 6, fontSize: 14, color: "#495057" },
  label: { fontWeight: 600, width: 36, color: "#212529" },
};
