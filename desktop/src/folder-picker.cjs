/** The renderer can request one directory dialog, never arbitrary IPC. */
function createProjectFolderPicker({dialog,getWindow,allowed,defaultPath}){
 let pending=null,lastFolder;
 return async event=>{
  const window=getWindow();
  if(!window||window.isDestroyed()||!allowed(event)||event.sender!==window.webContents||event.senderFrame!==window.webContents.mainFrame)
   throw Error('Folder selection is only available to the active workbench');
  if(pending)return pending;
  pending=(async()=>{
   const choice=await dialog.showOpenDialog(window,{
    title:'打开项目文件夹',buttonLabel:'打开项目',defaultPath:lastFolder||defaultPath(),properties:['openDirectory']
   });
   if(choice.canceled||!choice.filePaths.length||window.isDestroyed())return null;
   lastFolder=choice.filePaths[0];return lastFolder;
  })();
  try{return await pending;}finally{pending=null;}
 };
}
module.exports={createProjectFolderPicker};
