(function(){
  const esc=value=>String(value??'').replace(/[&<>'"]/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
  const labels={es:{copied:'Enlace copiado',error:'No se pudo compartir',login:'Inicia sesión con GitHub para crear un enlace',prompt:'Copia este enlace'},en:{copied:'Link copied',error:'Could not share',login:'Sign in with GitHub to create a link',prompt:'Copy this link'},pt:{copied:'Link copiado',error:'Não foi possível compartilhar',login:'Entre com GitHub para criar um link',prompt:'Copie este link'},ru:{copied:'Ссылка скопирована',error:'Не удалось поделиться',login:'Войдите через GitHub, чтобы создать ссылку',prompt:'Скопируйте эту ссылку'}};
  const locale=()=>document.documentElement.lang||'es';
  const label=key=>(labels[locale()]||labels.en)[key]||labels.en[key];
  function reset(button){button.removeAttribute('data-shared');button.removeAttribute('data-error');if(button.dataset.shareLabel)button.setAttribute('aria-label',button.dataset.shareLabel)}
  async function copyFallback(url){if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(url);return true}window.prompt(label('prompt'),url);return false}
  async function share(button, endpoint, fallbackTitle){
    if(button.disabled)return;
    const original=button.innerHTML;
    reset(button);
    button.disabled=true;
    try{
      const response=await fetch(endpoint,{method:'POST',headers:{Accept:'application/json'},cache:'no-store'});
      let data={};try{data=await response.json()}catch(_){data={}}
      if(response.status===401){window.location.assign(`/auth/github/login?next=${encodeURIComponent(location.pathname+location.search)}`);return}
      if(!response.ok||!data.url)throw new Error(data.error||label('error'));
      let copied=false;
      if(navigator.share){
        try{await navigator.share({title:fallbackTitle||document.title,url:data.url});copied=true}
        catch(error){if(error?.name!=='AbortError')throw error}
      }
      if(!copied){
        copied=await copyFallback(data.url);
        if(copied){button.setAttribute('aria-label',label('copied'));button.dataset.shared='true'}
      }
    }catch(error){
      button.setAttribute('aria-label',error.message||label('error'));
      button.dataset.error='true';
    }finally{
      button.disabled=false;
      button.innerHTML=original;
    }
  }
  function init(){document.querySelectorAll('[data-share-endpoint]').forEach(button=>{if(!button.dataset.shareLabel)button.dataset.shareLabel=button.getAttribute('aria-label')||'';button.addEventListener('click',()=>share(button,button.dataset.shareEndpoint,button.dataset.shareTitle))})}
  window.FoundstoreShare={init,share};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
}());
