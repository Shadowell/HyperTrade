import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type AssistantMarkdownProps = {
  source: string;
};

function AssistantMarkdown({ source }: AssistantMarkdownProps) {
  return (
    <div className="message-copy message-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noreferrer">
              {children}
            </a>
          )
        }}
      >
        {source}
      </ReactMarkdown>
    </div>
  );
}

export default AssistantMarkdown;
