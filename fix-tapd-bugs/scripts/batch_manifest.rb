#!/usr/bin/env ruby
# frozen_string_literal: true

# 冻结无人值守交付批次。只写调用方指定的仓库外 manifest，不执行 Git 提交、
# TAPD 写回或打包；可由技能在完成成功子集 commit 后重复调用。

require "digest"
require "fileutils"
require "json"
require "open3"
require "optparse"
require "pathname"
require "time"

options = { bugs: [], commits: [], bug_commits: [] }
parser = OptionParser.new do |opts|
  opts.banner = "用法：batch_manifest.rb --repo PATH --batch-id ID --out PATH --state-path PATH [--bug ID=URL]... --commit SHA..."
  opts.on("--repo PATH") { |value| options[:repo] = value }
  opts.on("--batch-id ID") { |value| options[:batch_id] = value }
  opts.on("--out PATH") { |value| options[:out] = value }
  opts.on("--state-path PATH") { |value| options[:state_path] = value }
  opts.on("--bug ID=URL") { |value| options[:bugs] << value }
  opts.on("--bug-commit ID=SHA") { |value| options[:bug_commits] << value }
  opts.on("--commit SHA") { |value| options[:commits] << value }
  opts.on("--description TEXT") { |value| options[:description] = value }
  opts.on("-h", "--help") { puts opts; exit 0 }
end
parser.parse!

%i[repo batch_id out state_path].each do |key|
  abort "错误：缺少 --#{key.to_s.tr('_', '-')}" if options[key].to_s.empty?
end
abort "错误：至少需要一个 --commit" if options[:commits].empty?

repo = File.expand_path(options[:repo])
abort "错误：不是 Git 仓库：#{repo}" unless File.directory?(File.join(repo, ".git")) || system("git", "-C", repo, "rev-parse", "--git-dir", out: File::NULL, err: File::NULL)
out = File.expand_path(options[:out])
state_path = File.expand_path(options[:state_path])
abort "错误：out 必须是绝对路径" unless Pathname.new(options[:out]).absolute?
abort "错误：state-path 必须是绝对路径" unless Pathname.new(options[:state_path]).absolute?
abort "错误：out 不得位于仓库内" if out.start_with?(repo + File::SEPARATOR)
abort "错误：state-path 不得位于仓库内" if state_path.start_with?(repo + File::SEPARATOR)

def canonical_path(path)
  return File.realpath(path) if File.exist?(path) || File.symlink?(path)
  File.join(canonical_path(File.dirname(path)), File.basename(path))
end

def git(repo, *arguments)
  output, status = Open3.capture2e("git", "-C", repo, *arguments)
  abort "错误：git #{arguments.join(' ')} 失败：#{output.strip}" unless status.success?
  output
end

repo = File.realpath(git(repo, "rev-parse", "--show-toplevel").strip)
[out, state_path].each do |path|
  resolved = canonical_path(path)
  abort "错误：状态或 manifest 不得通过符号链接进入仓库" if resolved == repo || resolved.start_with?(repo + File::SEPARATOR)
end
abort "错误：冻结 manifest 已存在，请使用新批次 ID" if File.exist?(out)
abort "错误：batch-id 格式非法" unless options[:batch_id].match?(/\A[a-zA-Z0-9][a-zA-Z0-9_.-]*\z/)
sha_mapping = options[:commits].to_h { |sha| [sha, git(repo, "rev-parse", "--verify", "#{sha}^{commit}").strip] }
options[:commits] = sha_mapping.values.uniq

options[:commits].each do |sha|
  git(repo, "cat-file", "-e", "#{sha}^{commit}")
  abort "错误：commit 不在当前 HEAD 可达历史：#{sha}" unless system("git", "-C", repo, "merge-base", "--is-ancestor", sha, "HEAD", out: File::NULL, err: File::NULL)
  abort "错误：冻结 commit 不得为 merge commit：#{sha}" if git(repo, "show", "-s", "--format=%P", sha).split.length >= 2
end

status = git(repo, "status", "--porcelain=v1", "-z")
diff = git(repo, "diff", "--binary")
staged_diff = git(repo, "diff", "--cached", "--binary")
untracked = git(repo, "ls-files", "--others", "--exclude-standard", "-z").split("\0").sort.map do |path|
  absolute = File.join(repo, path)
  "#{path}:#{File.file?(absolute) ? Digest::SHA256.file(absolute).hexdigest : 'missing'}"
end.join("\n")

bugs = options[:bugs].map do |value|
  id, url = value.split("=", 2)
  abort "错误：--bug 必须为 ID=URL" if id.to_s.empty? || url.to_s.empty?
  { "id" => id, "url" => url, "commit_shas" => [] }
end

options[:bug_commits].each do |value|
  id, sha = value.split("=", 2)
  sha = sha_mapping.fetch(sha, sha)
  bug = bugs.find { |item| item["id"] == id }
  abort "错误：--bug-commit 必须引用已有 --bug 且格式为 ID=SHA" if bug.nil? || sha.to_s.empty?
  abort "错误：--bug-commit 的 SHA 不在 --commit 集合中" unless options[:commits].include?(sha)
  bug["commit_shas"] << sha
end
abort "错误：每个 Bug 必须提供 --bug-commit ID=SHA 映射" if bugs.any? { |bug| bug["commit_shas"].empty? }

manifest = {
  "schema_version" => 1,
  "batch_id" => options[:batch_id],
  "configuration" => "Debug",
  "state_path" => state_path,
  "bugs" => bugs,
  "commit_shas" => options[:commits],
  "source_head" => git(repo, "rev-parse", "HEAD").strip,
  "source_fingerprint" => Digest::SHA256.hexdigest([status, diff, staged_diff, untracked].join("\0")),
  "created_at" => Time.now.utc.iso8601
}
manifest["description"] = options[:description] unless options[:description].to_s.empty?

FileUtils.mkdir_p(File.dirname(out), mode: 0o700)
abort "错误：manifest 请放在当前用户专用的 0700 批次目录" unless File.stat(File.dirname(out)).uid == Process.uid && (File.stat(File.dirname(out)).mode & 0o077).zero?
temporary = "#{out}.tmp-#{Process.pid}"
File.open(temporary, File::WRONLY | File::CREAT | File::EXCL, 0o600) { |file| file.write(JSON.pretty_generate(manifest) + "\n") }
File.rename(temporary, out)
puts out
