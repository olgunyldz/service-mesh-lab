-- Edge kayıtları: yalnızca log.name etiketli container'lar; zone ve kategori eklenir, hassas değerler maskelenir.
local function mask(s)
  if type(s) ~= "string" then return s end
  s = s:gsub("[Bb]earer%s+[%w%-%._~%+/]+=*", "Bearer ***")
  s = s:gsub("eyJ[%w%-_]+%.[%w%-_]+%.[%w%-_]*", "***jwt***")
  s = s:gsub("__Host%-sid=[^;%s\"]+", "__Host-sid=***")
  return s
end

function enrich(tag, ts, record)
  local attrs = record["attrs"]
  if type(attrs) ~= "table" or not attrs["log.name"] then return -1, ts, record end   -- edge dışı container
  local name = attrs["log.name"]
  record["kubernetes"] = { namespace = "edge", pod = name, container = name }
  record["zone"] = (name == "branch-fw") and "branch" or "edge"
  record["cluster"] = "edge"
  record["category"] = attrs["log.category"] or "network"
  record["attrs"] = nil
  record["log"] = mask(record["log"])
  -- ModSecurity engellemesi (kural ID'si satırda)
  if name == "edge-waf" and type(record["log"]) == "string" and record["log"]:find("ModSecurity: Access denied", 1, true) then
    record["security_copy"] = "yes"
  end
  return 1, ts, record
end

function to_security(tag, ts, record)
  record["category"] = "security"
  record["security_copy"] = nil
  record["copied_from"] = "network"
  return 1, ts, record
end
