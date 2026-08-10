// ChannelAdapter: the interface every messaging channel implements so the
// Gateway's pairing + dispatch logic (index.ts) never needs to know which
// platform a message came from. See ARCHITECTURE.md section 3.1.

export interface IncomingMessage {
  channel: string;
  externalId: string;
  text: string;
}

export interface ChannelAdapter {
  readonly name: string;
  start(onMessage: (msg: IncomingMessage) => Promise<void>): Promise<void>;
  stop(): Promise<void>;
  sendMessage(externalId: string, text: string): Promise<void>;
}
