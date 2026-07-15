use futures_util::StreamExt;
use reqwest::{header, Client};
use serde::Serialize;
use serde_json::{json, Value};
use tauri::ipc::Channel;
use url::Url;

const MAX_PROMPT_LENGTH: usize = 8_000;
const MAX_SSE_BUFFER: usize = 1_048_576;

#[derive(Serialize)]
pub struct ConnectionResult {
    status: String,
    service: String,
}

pub fn build_client() -> Result<Client, String> {
    Client::builder()
        .connect_timeout(std::time::Duration::from_secs(10))
        .user_agent("HyperTrade-Desktop-Bot/0.1")
        .build()
        .map_err(|_| "无法初始化桌面网络客户端".to_string())
}

pub async fn check_connection(client: &Client, api_base: &str) -> Result<ConnectionResult, String> {
    let endpoint = api_endpoint(api_base, "api/health")?;
    let response = client
        .get(endpoint)
        .timeout(std::time::Duration::from_secs(12))
        .send()
        .await
        .map_err(|_| "无法连接 HyperTrade 服务".to_string())?;
    if !response.status().is_success() {
        return Err(format!(
            "HyperTrade 健康检查返回 HTTP {}",
            response.status()
        ));
    }
    let payload = response
        .json::<Value>()
        .await
        .map_err(|_| "HyperTrade 健康检查响应无效".to_string())?;
    Ok(ConnectionResult {
        status: payload
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("unknown")
            .to_string(),
        service: payload
            .get("service")
            .and_then(Value::as_str)
            .unwrap_or("hypertrade-api")
            .to_string(),
    })
}

pub async fn stream_agent(
    client: &Client,
    api_base: &str,
    prompt: &str,
    idempotency_key: &str,
    on_event: Channel<Value>,
) -> Result<(), String> {
    validate_run_input(prompt, idempotency_key)?;
    let endpoint = api_endpoint(api_base, "api/agent/runs/stream")?;
    let response = client
        .post(endpoint)
        .header(header::ACCEPT, "text/event-stream")
        .header("Idempotency-Key", idempotency_key)
        .json(&json!({ "prompt": prompt }))
        .send()
        .await
        .map_err(|_| "无法连接 HyperTrade Mission 流".to_string())?;
    if !response.status().is_success() {
        return Err(format!(
            "HyperTrade Mission 返回 HTTP {}",
            response.status()
        ));
    }

    let content_type = response
        .headers()
        .get(header::CONTENT_TYPE)
        .and_then(|value| value.to_str().ok())
        .unwrap_or("");
    if !content_type.starts_with("text/event-stream") {
        return Err("HyperTrade Mission 未返回事件流".to_string());
    }

    let mut stream = response.bytes_stream();
    let mut decoder = SseDecoder::default();
    let mut terminal_received = false;
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|_| "HyperTrade Mission 事件流中断".to_string())?;
        for event in decoder.push(&chunk)? {
            terminal_received |= is_terminal_event(&event);
            on_event
                .send(event)
                .map_err(|_| "桌面窗口已关闭事件通道".to_string())?;
        }
    }
    for event in decoder.finish()? {
        terminal_received |= is_terminal_event(&event);
        on_event
            .send(event)
            .map_err(|_| "桌面窗口已关闭事件通道".to_string())?;
    }

    if !terminal_received {
        on_event
            .send(json!({
                "event": "error",
                "error": { "code": "stream_closed_without_terminal_event" }
            }))
            .map_err(|_| "桌面窗口已关闭事件通道".to_string())?;
    }
    Ok(())
}

fn api_endpoint(api_base: &str, path: &str) -> Result<Url, String> {
    if api_base.len() > 2_048 {
        return Err("HyperTrade 服务地址过长".to_string());
    }
    let mut base =
        Url::parse(api_base.trim()).map_err(|_| "HyperTrade 服务地址无效".to_string())?;
    if !matches!(base.scheme(), "http" | "https") {
        return Err("HyperTrade 服务地址只支持 HTTP 或 HTTPS".to_string());
    }
    if !base.username().is_empty() || base.password().is_some() {
        return Err("请勿在 HyperTrade 服务地址中包含凭据".to_string());
    }
    base.set_query(None);
    base.set_fragment(None);
    if !base.path().ends_with('/') {
        let normalized = format!("{}/", base.path());
        base.set_path(&normalized);
    }
    base.join(path)
        .map_err(|_| "无法构造 HyperTrade API 地址".to_string())
}

fn validate_run_input(prompt: &str, idempotency_key: &str) -> Result<(), String> {
    let prompt = prompt.trim();
    if prompt.is_empty() {
        return Err("研究问题不能为空".to_string());
    }
    if prompt.chars().count() > MAX_PROMPT_LENGTH {
        return Err(format!("研究问题不能超过 {MAX_PROMPT_LENGTH} 个字符"));
    }
    let valid_key = !idempotency_key.is_empty()
        && idempotency_key.len() <= 128
        && idempotency_key
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-' | b'.'));
    if !valid_key {
        return Err("研究请求幂等键无效".to_string());
    }
    Ok(())
}

fn is_terminal_event(event: &Value) -> bool {
    matches!(
        event.get("event").and_then(Value::as_str),
        Some("final" | "run_completed" | "error" | "task_controlled")
    )
}

#[derive(Default)]
struct SseDecoder {
    buffer: Vec<u8>,
}

impl SseDecoder {
    fn push(&mut self, chunk: &[u8]) -> Result<Vec<Value>, String> {
        self.buffer.extend_from_slice(chunk);
        if self.buffer.len() > MAX_SSE_BUFFER {
            return Err("HyperTrade Mission 单个事件超过桌面安全上限".to_string());
        }
        let mut events = Vec::new();
        while let Some((frame_end, delimiter_len)) = find_frame_delimiter(&self.buffer) {
            let frame = self.buffer.drain(..frame_end).collect::<Vec<_>>();
            self.buffer.drain(..delimiter_len);
            if let Some(event) = parse_frame(&frame)? {
                events.push(event);
            }
        }
        Ok(events)
    }

    fn finish(&mut self) -> Result<Vec<Value>, String> {
        if self.buffer.is_empty() {
            return Ok(Vec::new());
        }
        let remaining = std::mem::take(&mut self.buffer);
        Ok(parse_frame(&remaining)?.into_iter().collect())
    }
}

fn find_frame_delimiter(buffer: &[u8]) -> Option<(usize, usize)> {
    buffer
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .map(|position| (position, 4))
        .or_else(|| {
            buffer
                .windows(2)
                .position(|window| window == b"\n\n")
                .map(|position| (position, 2))
        })
}

fn parse_frame(frame: &[u8]) -> Result<Option<Value>, String> {
    let text = String::from_utf8_lossy(frame);
    let data = text
        .lines()
        .filter_map(|line| line.strip_prefix("data:"))
        .map(str::trim_start)
        .collect::<Vec<_>>()
        .join("\n");
    if data.is_empty() {
        return Ok(None);
    }
    serde_json::from_str::<Value>(&data)
        .map(Some)
        .map_err(|_| "HyperTrade Mission 事件 JSON 无效".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalizes_api_endpoint_without_accepting_credentials() {
        let endpoint = api_endpoint("https://example.com/hypertrade", "api/health").unwrap();
        assert_eq!(
            endpoint.as_str(),
            "https://example.com/hypertrade/api/health"
        );
        assert!(api_endpoint("file:///tmp/socket", "api/health").is_err());
        assert!(api_endpoint("https://user:secret@example.com", "api/health").is_err());
    }

    #[test]
    fn decodes_split_and_crlf_sse_frames_in_order() {
        let mut decoder = SseDecoder::default();
        assert!(decoder
            .push(b"event: answer_delta\r\ndata: {\"event\":\"answer_")
            .unwrap()
            .is_empty());
        let events = decoder
            .push(b"delta\",\"text\":\"ok\"}\r\n\r\ndata: {\"event\":\"final\"}\n\n")
            .unwrap();
        assert_eq!(events.len(), 2);
        assert_eq!(events[0]["text"], "ok");
        assert!(is_terminal_event(&events[1]));
    }

    #[test]
    fn rejects_unbounded_frames_and_invalid_idempotency_keys() {
        let mut decoder = SseDecoder::default();
        assert!(decoder.push(&vec![b'x'; MAX_SSE_BUFFER + 1]).is_err());
        assert!(validate_run_input("research", "bad key with spaces").is_err());
        assert!(validate_run_input("", "desktop_run_1").is_err());
    }
}
