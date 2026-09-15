(async function route(){
  await loadBranding();
  const parts=location.pathname.split('/').filter(Boolean);
  if(parts[0]==='mat'&&parts[1]) initSecretary(Number(parts[1]));
  else if(parts[0]==='board'&&parts[1]) initBoard(Number(parts[1]));
  else if(parts[0]==='public'&&parts[1]) initPublic(Number(parts[1]));
  else initAdmin();
})();
