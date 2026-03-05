FROM node:20-alpine

WORKDIR /app

# 依存関係を先にインストール（キャッシュ活用）
COPY package.json .
RUN npm install

# ソースをコピー
COPY . .

# 開発サーバー起動（ホットリロード有効）
CMD ["npm", "run", "dev"]
