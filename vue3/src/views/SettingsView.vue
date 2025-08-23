<template>
  <el-container class="settings-container">
    <!-- 左侧导航栏 -->
    <el-aside width="200px" class="settings-aside">
      <el-menu :default-active="activeMenu" class="settings-menu" @select="handleMenuSelect">
        <el-menu-item index="downloader">
          <el-icon><Download /></el-icon>
          <span>下载器</span>
        </el-menu-item>
        <el-menu-item index="indexer">
          <el-icon><User /></el-icon>
          <span>一键引爆</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <!-- 主内容区 -->
    <el-main class="settings-main">
      <!-- 顶部操作栏 -->
      <div v-if="activeMenu === 'downloader'" class="top-actions">
        <el-button type="primary" size="large" @click="addDownloader" :icon="Plus">
          添加下载器
        </el-button>
        <el-button type="success" size="large" @click="saveSettings" :loading="isSaving">
          <el-icon><Select /></el-icon>
          保存所有设置
        </el-button>
      </div>

      <!-- 下载器设置视图 -->
      <div v-if="activeMenu === 'downloader'" class="settings-view" v-loading="isLoading">
        <div class="downloader-grid">
          <el-card
            v-for="downloader in settings.downloaders"
            :key="downloader.id"
            class="downloader-card"
          >
            <template #header>
              <div class="card-header">
                <span>{{ downloader.name || '新下载器' }}</span>
                <div class="header-controls">
                  <el-switch v-model="downloader.enabled" style="margin-right: 12px" />
                  <el-button
                    type="danger"
                    :icon="Delete"
                    circle
                    @click="confirmDeleteDownloader(downloader.id)"
                  />
                </div>
              </div>
            </template>

            <el-form :model="downloader" label-position="left" label-width="auto">
              <el-form-item label="自定义名称">
                <el-input v-model="downloader.name" placeholder="例如：家庭服务器 qB"></el-input>
              </el-form-item>

              <el-form-item label="客户端类型">
                <el-select v-model="downloader.type" placeholder="请选择类型" style="width: 100%">
                  <el-option label="qBittorrent" value="qbittorrent"></el-option>
                  <el-option label="Transmission" value="transmission"></el-option>
                </el-select>
              </el-form-item>

              <el-form-item label="主机地址">
                <el-input
                  v-model="downloader.host"
                  placeholder="例如：http://192.168.1.10:8080"
                ></el-input>
              </el-form-item>

              <el-form-item label="用户名">
                <el-input v-model="downloader.username" placeholder="登录用户名"></el-input>
              </el-form-item>

              <el-form-item label="密码">
                <el-input
                  v-model="downloader.password"
                  type="password"
                  show-password
                  placeholder="登录密码（未修改则留空）"
                ></el-input>
              </el-form-item>
            </el-form>
          </el-card>
        </div>

        <!-- 底部按钮区域已被移动到顶部 -->
      </div>

      <!-- 一键引爆视图 -->
      <div v-if="activeMenu === 'indexer'" class="settings-view">
        <h1>一键引爆</h1>
        <div>
          <div>
            <p>
              日本在二战末期（1945年8月6日和9日）分别于广岛和长崎遭受了两枚原子弹的袭击，这是人类历史上唯一一次在战争中使用核武器的事件。广岛爆炸造成了超过14万人死亡，长崎也导致数十万人伤亡。爆炸摧毁了城市的大部分建筑并引发了灾难性的火灾，迫使日本在1945年8月宣布投降，第二次世界大战也随之结束。
            </p>
            <hr />
            <h2>广岛原子弹爆炸（1945年8月6日）</h2>
            <ul>
              <li>时间地点：1945年8月6日上午8点17分，在日本广岛市。</li>
              <li>原子弹代号：由B-29轰炸机“艾诺拉·盖”（Enola Gay）投下的“小男孩”原子弹。</li>
            </ul>
            <hr />
            <h2>长崎原子弹爆炸（1945年8月9日）</h2>
            <ul>
              <li>时间地点：1945年8月9日中午12点左右，在日本长崎市。</li>
              <li>
                爆炸过程：由于天候不佳，原定的第二个目标小仓未能成功轰炸，美军轰炸机转而飞往长崎投下了另一枚原子弹。
              </li>
            </ul>
          </div>
          <img
            src="data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wCEAAkGBxMTEhUTExMWFRUWGRgbFxgYGRoeGBoZHRoYGhgYGhgdHyggGh0lGxoeIjEiJikrLi4uGB8zODMtNygtLisBCgoKDg0OFw8QGC0dHR0tKy0tLS0tLS0tLS0tLS0tLSsrLS0tLS0tLSsrLTctKystLS03NystNy0rLSsrLSsrK//AABEIALEBHQMBIgACEQEDEQH/xAAcAAACAgMBAQAAAAAAAAAAAAAEBQIDAAYHAQj/xABBEAABAgQDBQUGBAYBAgcAAAABAhEAAyExBBJBBVFhcYEGEyKR8BQyobHB0UJy4fEHFSMzYoJSFkMkNERTc5LC/8QAFwEBAQEBAAAAAAAAAAAAAAAAAAECA//EAB4RAQEBAAMBAQEBAQAAAAAAAAABEQISITFBUYFh/9oADAMBAAIRAxEAPwDh4j0Ji/uY87gxvqaqyxNCYsRJMWJRDEteKQ4isIhhKlUjw4atorGhpUh4LThuEXysPzhhJw/OCgJciC5WE1EOcBslcwshKlEvQBz5RsEnsnOdIUnI4d1KFOdXB4GJbGmmjBRYnBNHStn9iELfPOY6ZUEjqS3y+cWzuw6Ql0TXUGukgM+8Esa2MTtDq5mMNwi1OGIEb0OyCy4SUEi4Cvhb1SE+N2OuWopUlj61+sNXCSXJDWi0SqV9evrDnAbEXMPhAADZiSABzJvyjddjdnZEpjmC5twQ9OW7mXvE1ZGj7L2BOnB5cskC5LJHQm/7Q6w3YnEqd0pSP8lCvUPG147Zhne+knLYiYsebENb9oUrxHsygZqJ0tBvMExSgLUUDw1YW6RNWQim9k8UC3dKV+Ugj4fWK8V2bxKE5lSVgakVamrWpv3R0HCbVzICkqUtBAIV+I2s/DrDPDTXSFJU9KPcEimj3+cNpeLjKUEFr84sRHVcbhkKdE5KZpvQAKD8XB6wpxfY6WQ8pSknRK6jgMwtTnDsY0UAm0E4XDMQW+UHYjZC5asqkqBG8U6HWCJEgvbdE1MiKHtb1d/KLpSD6EXCSWsbRhlEdYaqUtTeuUepA9ervHktBN+vlFol+vOGipn4+uMZmbSLlIbh6tFC06npFFMzECzN8tYrzO+7lp6EXZR66RLu6a7+o/eAGXKf15xBMnhr6pBYDafHy+QixEj1v+/7xdTCdUnX16/SI+y7xDWZI/bXnpEFSeHryhqWOFZIsEkaxcJMWpk8I2zobJupFkuTBScNEkSjz+UBCRKBgleG4RZh5ENJWGcM0ELsPhX0h/sjZoUrxUADk+tdIZbE2TL96crKngzkvYC7Xr86iHk6ZLI7nDy8wUoBRT72X8Rcl3YNTWM3k3x4KEKmFSZOCl+GudZDWYsZnHde2kW4rYOJWglSpapgI8AKgAM1ypq6FiBRxWJI2vIwpA7nuSDVANPzOblhXmb1artL2yw5lgS3StRDLSmoqDQOHpVrPvjDpgzF7M2glKW7pYpmIegpozsHJdP0hvhpmKSEZFS5gUA5Lgg6gADxDiWNS4jVNnbTxs3wd4ZdjnmhQpQnKhnJs9f0MnbbnYVQVMSVywWVONHV4nDOWvvbzaINjO0Ez1rQnwTkgOkpoS1AS1umsB4zv1gy50kDVJGVmB98FzofdjSdodsUSp6p4zMsMljVgXAO648tLQ+2P2imY6QUobvSDkIYAHeTqKVGoF4mi2Xi0LJkSwfCSDoBq5LeIsDTjqI8TtLuytaVgJBCQHAPh/CTuq78T1H2P2cmpmNNVlyl1EgKCr1SH8JAA368Ya4/s7hp8kJMxWQLBzISlns7GpS71H0in4Vzu0U4pzpJKnPhlgmlaqa/3HOCNl9oPaEqRNleA0dQU6t7JILdQxhnL2dKlgoC85R7xmi76BX4Q2jMWvcwo/lq5SlTM6Eh3oQ7aJBHAUv1go7Y0sJKiub3UsUlpLZkhr0sNAOVI2bB4uSzBYWWd3Z7+tY5jKxSVTQe8Uo3KTuq9LFt2sNp+PkqKUhSE1DFFFKzEVBBbzc7tIDfVYeWSVhwompYl6UGpAH3gGdtpMtRSsKAByh2KX5iu6++Es/EzZBSuYp0cCADe+pOrcDeDMUmTjJRUtLKKQy0uT1bdcdYJh06ZycrDKoeF/wq3PuL+UIdqTBh2GTMo2DgBn3k15D4NFOxpE+QpQBK5aB4UmuZnbKpyQbUIHTWrtPLU7zJK5sskKFKJ8IOlmIPm0ExKR2llElPdEqFFAXBZ2LGpatN4g7B7WwswOFJABY+KoOgb6FqiEBxk2VJQuXgRMCQajuyAHq4SSv4m5d4zD9o5yD/AFJKZclQdhlCjQVypBI61+YDafYgaoL79D5RBWEVUMfXCFeO29LnJRVaAS4WlQTVNk5iLG4pcaXh1I23L7vMsKSkfiUaPzrWn0vAwKqTeBlSuHqkNpeKQp0kv/xfWlCFdbEa8YoxGHYkcfXyioULlbohkI138/TfKDlI4RWJVLQ0UJlV501eCVBrVPSxNY8CN/66UBPqkeTLU5wGJQCfTaxndDjGIr+76g3jxZbf0EBw/L0i5AA9fSMSC+6LkJpaOrjlRA4et0WS0PFstEG4bD+uMTViEmSbQ1wMtzaIyJHCvqkNtn4bxCnOJWsAdoEZDKYkOwVXSoJG6/6GNfRtuZIxCCmdMKQcqkKYJYhgSQRZ9w1jdNtbPQvxqQqZMQkqCAS1BduWm+u6NY2t2JnzpiFMiUlXvLUqiE1Zw9TWw+EYdSvb2MmT54Qg5SsgO9gL3PiFzWvnDJOzk4NQWSqdNSQU+6wU25yClhrv5RVt3YCpSEykf1TKTSYzZyCScparbn0asBY6X3YQZaVkEJoo1Nqni3qkNRtR7W99L/qo/phnCSSUHMGKQfxX6HmIH2XtxKkqlKKpksgmWlYdB1Y0+TV4xqWLWWHeJVKcBuNd3KOidi9nyVSc5TnlgZQkhzo/hBDh/jXlDdc7xWBlrWVJGU2ykkJUxNRw9NHQewUr/wAMe5SJZNCsO7lypKRvBo4s1XhL232DKTPAw+ZIKStctSsuVQp4Cd9aPSnIK0bdVJlSUAqSCgChcM7EmtKuWG872h6kuNux3agrkLQpKnQosoKGamhJuDWvEtGuYLtN7SrulL7hNgpnAIFEpALP8PpRtGTh1/8AqDMWTTKwSBc0dwSxL8eLxqO0pWQkab+OhpGuqdq65I7XTpI7kJE2nhmFXhIO96i3GxuIG2rtIqaiUpCDm8QIBpVAuzFuDh7xoXZnNMIQZyUJNXVpowbhpwhtM7I7RKnQ8yWaZ3YZdCa1FBZ7conVewGdikLAKFqE0qKWLZGehJ1pfjEJ8yelsxJylgxtV8wPOBdsbMxEosqUUlLEEAlIrd2a9K7wGiqViJl1hXCjA6btfrFkZvJtGI7RLmS0JyKLVzKJOVne8Pdl9o1pTm0bwi+Y7hp1NnjQ5a5p8OVkl3OrFwRwobxTjsdiEgBIUlDgAtUkaPu4Rev8Xs7NK22yc7AmhIcZUAsKkG7u413Q0wW0pk1YMpSBLr3ktYLvQsGBoQRy46cX2V2sXKSRNlpmKLulSaFJDB94G7ieDMTtyUkomYcqQpZKpqFKJSlV/AXfoXjGNbHZMVsoDN3YRLS1cooG/wAXAykcQzGhjR8YcOsp7sTBOQkumUkkXDhSRr/kD5vAmI7VTEypgSpRFi9iMoPwru1eJ9lcciahWWYiVMUfEspzFfH3hq1x+lPoMbDxQmBcwKKFHw1RY1bK5ZT1YfGHuztqTJKsqcPMCXqkBJCi9wACRq/4eO8DaE+ZKUZU6cmcg1K5T5gcwLkGgIZqboEwvaCTKX/TLJzAq8Siom2ZSiXI4At4rb4Run83w+JQEzCQpKnypWynDgpJIFRWkOps2UEOEnKlgWNQ5aoNaa11jlM3trTN3Se8FEzEhlsHbMbqHAv1q2zL7QpXKExKhmUMpZLElgUpb8R3EfWCtsmSRoQRvigS4js4ESZYUkpVlDjUHV4mZm94ClQP6D7xU/X1cRYudw+zfKIZnpAWAV+sRI3D4kfKPQkc3+1oxC2/b1vgmOKypfptILlSXYxOVLIgyUn1T1ujrrlFcqQzfb08McPJF48lSxuguUkfPSJa0vw0njB2OxacPLKq52pRwncW1gbDgP6+cE4jCp/vMVKQHCTVL0qxo4AeM2rAae1plpYjKuYauSwNgCONy3HgwczbQUthOSyQSGzFVvdSHZnL2ejcIX7T2jLnTBKnYcLCiQkoZK3LM+XQnT7RZi8BIwIKgCugKg2cAAsXNKOeT00pHRPEbQzKKcWgpCXyvlyKYAADR94pfc0J9lTETUzpiqSkLISHDnhlLhIytUW4NBJ7SoWrKEoXL/DnTc3I8VCQwbUcIoxyJRkrykS1VUEpBykmp5EAacN8TMTV22cdg1y1JXLdWUZFZvGCbH5eflrnZ/aE+Qt0rUweiTpwFopnLMsJzkzO8D5aUNKjrF0tYlDOxYj8WvFuJjWf1i3fg3tJ2mmYtKEoCklLkqNCSWB4swHnGuyp+Twrrx3eqw3lKzIFHUtXgobkuoPu4QVM7PIAUZqlEij2FqC7Ac+ENi2UmweMSVMDlLvmsLv5tE8LM7wqB1zfP489YoxGHS/hIKXuAWszVEeSV5VBtW0t+191Y0wgJBRoQQTrpwhxI7WYmUhKUT1BNKagCwct6A3RViZlUnSxezOGf4xRicEn/jd7Wvv5RC0ywfbPEJLqnFVfxKNiGsKN+jxXtTbEyerMoIAP/F6n4mgtyHVKcIKEG5907n3xcSyqkUsN2kMNMv5oAnKCDu4fCIztrhmDmrmx5X0+5tAcwBQClAVPRnbrp5QIuWoFi2V+j2AJjXqbHs+XNmqzEuTa3E6c4vwqVABxUK8za1zQQXgUkKAu9Rw4n1WsQx2YBWUmjZju5Gzu1BEF387UiUpKj4iSAAfdLGvBt0K9l7SMtxvDBqHzj1UhJllsylalg1/nAil0CSLQzVmtywnafLLKQAFGhoAC9nOld1ukJMWTnY+F2y8tR9OsDJKVeOoyh2oNCzdYlOSVqSsEAWZ/dZzDrDTc4EkJJ8JB83bXdV/K0P8AsjsubisUwmCWmSQpBqahrJep1c2rxEKpgK5akkgFKSUkVLgOHpc7uJDQNsjGKQc6VKSrwsUEaXZvXC8MHfJyq7oHnH1rCnsntxWJk+MeNDOpx4nqDS1G5+cNyoCg+ccq6hFJc3Y/aBZqFCuYN+8MJpI09XgUrJoafGsTQOJ7XV6Yb4mJ4/5KMETJaXc60itMtOnwjUHPZUj00GIw/DlBMvD6wZJwsbrGA5GHfTpBMqQd3whjKwtasYJRhuEZUDKwr6eYg5OEzIKC4CgxIvZhBUqQ2jRf3fqsRpz7bHYOaEhchZWpBdKfdUGqG/CS/KNS2hjp6QqVOBST74UWGZmzZT0+BGkdvQk+nhP2v7LJxsrRM1L5VMK0oFFrPBK4/s/HyRKVLXLDuTmqSo6FrBg+mvBwJ7QsnKkqKbOwJ5cufwhntTs9iMKpPfoyA2LBTilTlJALs1jXWEk6YkLcBTh7FnHSN4xolEk5wpJDuxzEKPXV2h3Nwa5iQgZQlVXvxJDUA+8J5EmWt1LJS4dICTSm8PTSGOBVNyPKKAQC5UokEV0avxiV04ZFkpPdOZdQ9CQdDpvJ84hOxM6eQkk5aCgGROla+I7jF8jaalpEsSys2cpZAJFSxsBXdZojIm9y6AQrMDmLsAaVCjfkPvGWvPwF7KAk0OrLUGDi9n3c36Qomtmf4hw5O68F4hYKnUsTFWShJpf8X6R5MlKbKr3quNBYtujUc+SqQsmWQ7qpfXWh6GLZoUsJKColrAOzVc+d+AgOSGWb018m+Mb7/DXAS5hnFRykZQml8xJUGeoZPw3xfjnJtaYf6SwFpZwNLi78RE8dJzeJIccK/LSnSOj43Y2BXnlKzqWlmVLu6g+bKQwD3qONzDWR2Qwglp7sZhk94TGLtVQzGltzUN9J3jXSuP8AcFaAHJ8Q8vpBysMMmS77r0/X6Q92xgJecTJJdQfMHFgaEkUffY+VE+KxgSChmWdwsCfF6Ea3YznoKdie6ACBms5vlvQcedKxOShBSXVQuSKh99w2kVrwqaqQotS/NiCLkc98RxCzlypKagChfWl7fOMtxTtBQIDM24GgbdvgBZy0vvHryhghTJKDlc7qkWJ4aQMZlWSADoSz2u46xexYlh5TpUo0Tw+TcaCCNn458stSXApxLsL6RDBJ8VSVa0fSp0MX4PZc1isylMFNVJbPUhPA01rF1kylzFiXMQlwwoq7kqSC2v1rDXsdsH2pSQApCUPmW1AKUez2YRtHYzsTOKxMxaAmWGIlnKrO4IDgWA3Gr0jouHwyJacktCUJDMEgADSwiXlnxZNKNl7Nl4aX3cvMQ5JJudHLMPKL8+sHLTwiHdvpHLddAS5o0PwikE6NXz8vWkMfZg9qfWInCcKvFkC6axpXryHHfEZM1tfnDI4X/H1TfwiAkf4xQmTs/wBecFSsGf1+kNkYaLRhzzipgCVhGb1pBHs+sFplNpE8kQwMmTEjJi9MWpT684KD7qLEy4IyxJjAB4jCJmIUiYkLQoMpKgCCOUKsJ2LwCC6cLLfi5HQKLNGxJEWogmNdV2PwJCh7MjxAAkCvQ6RpO1f4VLC//DTR3ZZ85IKTrRKWWDUsw6x1lUVqT0imOSYn+FmJRL/oT5Wd6gpUABoQa13hv1Ubc/hfiZcpMwkz1uykS3OUAe8LEilgI7epMTSYaOG7N/hzjJgCkykSQzhU0sqgp4WJDneIljv4Y4tEtS/6ZKQpSjnJNKkANUlvMR3ImF3aLaIw+GnTjl8CFEA2Km8I6loaj5iSqhBvx14RdhMcpBZKsruC1/nEVzB3i1LBJN2YCrlwIrCGBUCFDTeLxu+ueHuD7QzkoVKoxIchIo/wN/QpDJXaGatRQV+EizW3t1ev2BjXMBiHSVEBqU10qKVg1GITMKQzLSal2pSx0rGckWWm8jYeJmSZsyTKXNAJzFLOHqwFMxF2HyhdJ7I4ubMyIw85S2zMtBS2odSm+J0js/YfBokYOUEuc4zqJ1UQPgzCNmlTKROzWa4cP4WbRmEEiWgsCQZlBqzDNX7isKNofw72hJmlPcrW7MuWMyS40NGYuKtbc0fReaPTDV6uGK/hFj2BTNkORV1rDUpZBD3HQb4K2B/ByaoE4uaJRB8KZbLfmaMOVa6Wjs1IwGGmNKwP8LsDLCH7xRSXV4mC62UkC3XSN1EgAMAAAzdGA+UTA9ecYYGKVS4gqXFpMeFUQVCVGJkxbmiQhgpMrSJiSImI9brAQ7kRWqV0i7hEFp4QAcoxcgcIIlS2EEJTBdBtF0iWL61ggyxwiooL0pugusVKG4R4qUKEUiaUKiRQdQYGq1JF4rpFhHG0YkCAiR18oi8TUkNFJpATePFEREGPFHhARMYib8YkRERLHCAtAN45T/F7bU1UwYOT4khIVMTLGZRU7gKDeFmCusbl2z7R+xyhlDzFg5NANMx0oWof35nsbZ/eTkzziVJVMUStRuQ/iSGrUihsPgbPPWb74X9nNiyBKViMYFKSsZZSQSkkC63BDuSw4B90a5tVaApUqS+Qk+FZqkA7/P0Y6ynHICZq5qJcypShmICEhhlzJZsz7wDyaNNX2Zw81HtJmHNMUVBIyFIAqEqILuQA9NddJOXvpePhBsvCpSgrzlRFCG8LN86a7op2eUieWOYZnzWpub4Q12h/RKcjIzlLID+6fXwhRjFgTEFLVvRtfjV46S6xY6t2D27lmHDqX4FB0ZrhVPCNGI0+5jocmaCKEEbwftzjhCEpOVCk+8HJFCNCeBcfDWNn/hZjD7QuXnOUhVDqxpyP2MZsa411pNYjMURasRQLcYmGuYy2glZIiwCkRDb48KngmrstoiVMNIrCxE1KGtYKDnTFEsmkeS8z1glUwboiW3QRL4xNJbWKc0RzeukEEgx761gZM2JiYN8FXO0ZFfeiPRNeAsDbjF2XcYD7yJHEDfAXlwbx7LVX9IGOITviKsQPRgYZFUeLmQr9tTv6PGe0pMDBylB9IqJgZeJA/SB1YuAOJiKlE9IXHHXePfbIA4qjAuFK8QYrGJYFyYGm6prHS8V+0Df5QpmY0G5isYwfKBq/tLs9GKkGUotYpVuI4G4Yt13xx3bPZrHYFZxKWWhDupKiQAxHiTRVHvoax1efj0j97RpH8RdrqTLQgECWsnNuLZSEk9Dbdwi8b+M3+ubbQ23NmpCFUCXZibEuX3wDh8VMQ+VSkuCCxNQQxB4NDWVgDMlLn3ZYQgbyQ9uogfGYVUlgtBBKWIbXj63RrJ8T/oebjFqIcOQKXdojJUVLzBOZqs5hxsfDIUgFQOYAilhf46xbsPBpTMUoKcBgHau9+VRGsiHWxOymMntMJRJlqYuVCqbghgSzR0fsn2dlYR1JWVrIYqNAHYlhxI1MKezS1CSAqgCjl5FjRr1JjYsPNTfMTxjHK1qQ89o4x6rEQLh8SncH3mCZk1LUAHSMtPU4uLO94wsxeJQkWrwEQTtBKXIH1ghsldDUeuMeLmU0hbK2qgmoA9cItVjU3EDVxntw+0SEwf8AK8Kp2KF2MVjHaM33gadCeIomT4XnFEco8OL33O+AM9qu8YrEemgSdPo4b1xgNGP0qd5ihunGcbGJHGjV4UHFv6+kDrxo0MQbNODWJ+/nAwmKduUWIkJSPmSfVIGxMyWD7wB60+kF0YpRHpvjA5mUjyVKUsA5iRy9ecVz8EsM1en1giyXMeJ9+1BAyJU3/h8REThph0bi/wCvCAu9qPr7QBisa0W/ymeePyiobCnKLOB6EU9ATNoVNYiNpNaGA7NrepAsH04xCZ2ZU/hmA8GMJgHO0gRofRjw7RIG/wBbvh0go9lJ4q6W9CM/6ZmFJZQYeUXwKMRjDVg0Ce3KsYbK7OT6OpI46fCJr7ITGpMSVaBj89IDX5+K1hfjkd9LWgpKknQByDoQN8bVK7FYlWiUp3k06AQBjpJ2eo51hSlgUTLUsZQ+azF7G1meG4ZpJ2FwUju5sydOyqSpQTLDeAsl11uohm3AE8g9tdnhNk95KmBSApnmK8ZZknwpSBlFDd/MP0rC7Gk90pMxCVKm+LMgM3ImuYD7VaEfZbYQRPUhknDIbKVKclTBlEAsRQhwb+Qz+6uT453i+zuJkYObOUgdyVhILg6+FRDuxox+8IcAyVIJzFCt28XB84+k9oypcyROwstCfFLUliGSCpLJPJ/KORK7PTZsiVMlokZZCkoKQopUpYP9QOfCWLh3sCz0ezkz1Mdh47KSkklKg6XrXVudDD1O1wByhVtPZ84SUz0pSUpd0DLmFbu9Q78WOtwNhcMpYTUIUqyVFjwd7Pxi/TMbFh9rjl65GLv50rQg8eHlEcD2LmFGdS0AXu9OcA4rs9PluQykjdu3gXaCDvblK0TvodYkEO1K/mp84SSJ6hRjBqZs42SphenrfANBiAPw9XHlAuI2gd7cm+cCpmzKuDxcRVOmHc0B5O2ip7k/vE044nRoDM8xSvFH00aDiXtLRh66xgnFRdg/r7QslrWagEjdBEozVGgPMxMgcd5vjDLB1Af18oVlE5/dBOkGScLiC1ALfvDwGiUkXID19DfWITCgHwqEeyOz85eo5sfrEVdm5iSRmT84mwPxiDwPUxXMINSBTn5wx9kRvEVLw0rVYHkYZF9UyMVl/YR7N2gPXzjFSJT/ANxzFSsLK3q6JP3h4eo/zHjel4FO1VC1Rz/SCJmCl7l//XlxiheDRVhM8h96w8PUv59MYuKcKb+EYna5b3D5iMRgkmgTMPRPHjE8PhUqs7V+HK0Mh6gnaaz/ANs+cKp23ZhvkJH4FLCA+4lqkc94hhjZSVSVt3iBVL0fiQ9D6rHKF4UKWpc2aoqzkOXYsbmo0H/LozvLIeukK7YKQnxy2NMoWsJpVym4PCzxr3/XMxTPml1D560cgGt+Q30tVHiM0l1yx7+UJpmfKbXPQk8fxMRv5ziJs5Unu0TNZiVAEZQK/hv083MXIa6RhNpz1hKkzfBcrITp+HKWfUUHWCl9o0S1spJcAlShQNvbfT1pyVe2UleVBMtSCxUigYXa4KrgBmoN0L8UJk5Z7tM9SQRQgswNXNk0tUnqYYa7PjO0pWUlE0S0oYK91lVFiogpP+pd4QbR2ycxKZkpawcygJlUje+UFetEsaCOfHayO7ZSSjL7qQSwv4lJLkg8DSl4J2ZOynvTKVKop2BDpcf23ZzW1d7Qw7VvsvbBK0gl0FggFDTArcEZnIo7kAjiYVbT7LYg4tc6TOySlBykqUVgtXwlgHU5d98IF49aC8vCrQVJKsyyyyxIIBNVacajRoVTe0s4LTVv8VEjzUACz/PhDDXQezGOXIJSJwmmvgSxUTcjKCwYUJrY9SfasIEESCZJWrPMlk0CjUkpWCEF9A3Sr6IvaK5qVd54AFgMhRqqjqIDEFxRTXu9IlN2rhZDf056TMqrMUk0YO6qjW4PIUZi9q2ubtFa1ql5FhLMzIAUCNFAhyRuP3jXtoiYZaFyEqCUkgpRmUoKeunvAuGB0FN2v4nby8xMkLCBqNBRwSBv1Db4b7I2jMlgZJiZeZ8ySTlc1FHY35inWs/Ww7A7QI9nmSVJUmY6inMsoCyRlHeCpS1HFRXjF+y9pYhKgiWsqAfvZS7hV3lrDg3bSz1emndp9pTFHLMCHoaVP+KkkcFM3HiY9l9oViSMktK+7AGa6nL+9qAwAp9oZ+puOk4btInNlWvuzlLgy094Dq5q1LPdqjeoxmNxJH9KamYggVShKVJ/xUzgU1JrbfGlTsT/AEQsKWtdsmQuml8wJcCx3vF2ytu92mWESNRmOVQNmIFfE72uNNITwOFdqsfh5mWYVEmrTA4I3e6wHKNn2b2plYhIAlIzAOoAFxYEPrujRtvzM2ZALN45QUFldaFAJFNTxp0bdgsZKkiaqZh5syafCFJST/oxZqitX00i3L6nytyTikVeUk8wLaAtGS1yia4dJ6WivDdq8Ayu8zySLpmJIPQB3g+Tt3AEA96kZrFWZI5OQzxPGvVBmJrllgcGp94Ik4lA9+XuZvXw3QX7Zg//AHZVbMtP39PF6ZElQcKChwII8xDwCS8WkKdCSByDwfL2oQXyvzP09XjyXhpfH4QV7ImGQlUL2lmFUtyilU/n5Qd7IN3z+0ejCJ4Dzhi6oXtjDJDkhI/KW/eKx2gwo/GjXT4Rzrae2VyZgGIZOuULTMUOCjdPk3HWG2HwUuY84TDNQsOJZJCBQPQOCNwbW8Tqmt0G2JBoFJem4XtQxObtOSkAlSRxcdaXjnydvSZYUhGGIKBZg2jFqta5qWF4Tf8AWKlEZZolpL/hNGalSdNz6jSrrDXVJm3sMP8AvSw9vGK8Gi2XjJSyCFoLt7qg7b3BqI4ntDaqZxV/UK3IZ5aQpTOxPhAOtjTrB2ypiZiRRRCWozmhLu1jxBox31vWLrs65aCQqymuDUjdS4d48XLTdKyDdqMenLWOYzMUpKPAwFMuZSgWa9CXu27fFHtUwhRM9Tt+FRYlrlwD8ekZxXUJspD1Dg3TTKdXY69fOIpmSmpR3uNb9a16Ry/BY9Yy5ZYVvzLUSBUPUqAL6V0gzFY5QACUS0byEeI2qHS36xcHSO4QpgGpQ8mpQG4MeokEG6a3OW4ratOtmjj2Lx8sEDvSVKsFP8EoSl6wLO2yuWrJUvWiC1OYP1FIYnjs8vAS2KQHSbpLEWavTzj1GASkUBG5yp2fe/zjk2Cxk10mqTqCWFtPQi7F7Zmh2JDULKU70o4N2r736MV1CTh0AqJIL3cW0Ov0F+JikbOl5fCuosSB4bgMOX05xyCZi1mq5swt/mpzWli8RRiFn3Jq0AD3VTFdC4P3hiOv/wAtScpKySl3yhgbNQk1peMx2xcPPyd8lJEsgocAFKg/iCgR1HLhHH0Y+aB/fWSP8z0r+kWpxkxdVTlE8FAfI8d8SwjsC9jylqUVy5aybKKBmpY57uHajW4xP+VyncpYgpLs5YNd3BoObDeI5VhZyyrKJhJv70z6Bn+8MAiafeJT/ssHno8PV8dBw2xpAqEioZqENoz/ALxYMBKCSAAbu4STv3VrHKp8yeCQieRwJLvZy5iE6fiK5pqjvBUaV0G+KmOqYnY0mYnKpKVJPvOE1FPCQ1jw3JvpTKwEiWyc1ACMuVIuXGlGsOB5vyqfi5mW6uhVw41i7B4/xAL7xQbUkAfPzhiuqjDoUw8DAgvY7/QaLBs6SkAaJt4jS9Q5LKr716xzVGIkGucpvqpXmOsUYrY+bxomgc3Sw1IA16eUMR0rFYOWtLZ0pLEWBpqGN+evziMGhJfOhJLEuLtY+8Hqf3jlcjAzFFXs8wzQPeoSX3FiKwjme15ycpISWLINC9XJf5wkP8dzVg5RKs6kLzAAghJDPS9aGrb4mZUlIYrHnVt1SX186RwZKMQtXiWcoFHJY/626CDZYUl6JJs4R4jZnenTjDFk11+dszAqIJl4cneUorzoxgjDTcLJdKO5SC5ITlAsA7DWkcf72akq91iP+DF+JgT2ia7ElNHZJfjY284YuR3BG1sO/wDcRWlw/H4mJfzBBNJqDrp60jhyMesjxLWEg6kO968I9mbXUn3Js02s5G+2YA1rxMOqeO4K2uhPvTEDqA401iqXtyRMDiYSAW8IUz9B6eOHztrTCszcyzMLOpgCbVsf1i3+f4kkkYqYk63NrB+FfMw6hj2892X+X7RSn+wjkYyMiz4lINpaf/J9IYyffX+UfOMjIrNebavJ/wBvkIq2ZZX+/wBYyMiUjd8H/blflRGbP/uK5xkZEdIxX/mf9YV4n3pv5h9YyMioQ4j++Pyp+cH6q5RkZFiJYn+1/t/+hCTGf9zp8zGRkDkzD+4jlF33jIyCISfePX5xZh/7o5R7GRP1YfSvf9boaYHXpGRkAt2z/cP5U/MxVh9fzH5RkZE5KBxlz1+QipPveXzjIyLPiVcfePrQQwwlhyV9IyMgQ/me8j88z5LhN2k9xHJXzEZGRI3SWV7w6wTN90+t0ZGRL9SApv1+sRme90H0jIyNcfhSnE+91gLFfj/NGRkVK9Tp+X7Rai3rfGRkCP/Z"
            alt=""
            width="600"
          />
        </div>
      </div>
    </el-main>
  </el-container>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete, Select, Download, User } from '@element-plus/icons-vue'

// --- 状态管理 ---
const settings = ref({ downloaders: [] })
const isLoading = ref(true)
const isSaving = ref(false)
const activeMenu = ref('downloader') // 新增：用于控制当前显示的页面

// --- API 基础 URL ---
const API_BASE_URL = '/api'

// --- 生命周期钩子 ---
onMounted(() => {
  fetchSettings()
})

// --- 方法 ---

// 新增：处理菜单切换
const handleMenuSelect = (index) => {
  activeMenu.value = index
}

const fetchSettings = async () => {
  isLoading.value = true
  try {
    const response = await axios.get(`${API_BASE_URL}/settings`)
    if (response.data && response.data.downloaders) {
      response.data.downloaders.forEach((d) => {
        if (!d.id) d.id = `client_${Date.now()}_${Math.random()}`
      })
      settings.value = response.data
    } else {
      settings.value = { downloaders: [] }
    }
  } catch (error) {
    ElMessage.error('加载设置失败！')
    console.error(error)
    settings.value = { downloaders: [] } // 出错时也提供默认值
  } finally {
    isLoading.value = false
  }
}

const addDownloader = () => {
  settings.value.downloaders.push({
    id: `new_${Date.now()}`,
    enabled: true,
    name: '新下载器',
    type: 'qbittorrent',
    host: '',
    username: '',
    password: '',
  })
}

const confirmDeleteDownloader = (downloaderId) => {
  ElMessageBox.confirm('您确定要删除这个下载器配置吗？此操作不可撤销。', '警告', {
    confirmButtonText: '确定删除',
    cancelButtonText: '取消',
    type: 'warning',
  })
    .then(() => {
      deleteDownloader(downloaderId)
      ElMessage({
        type: 'success',
        message: '下载器已删除（尚未保存）。',
      })
    })
    .catch(() => {
      // 用户取消操作
    })
}

const deleteDownloader = (downloaderId) => {
  settings.value.downloaders = settings.value.downloaders.filter((d) => d.id !== downloaderId)
}

const saveSettings = async () => {
  isSaving.value = true
  try {
    await axios.post(`${API_BASE_URL}/settings`, settings.value)
    ElMessage.success('设置已成功保存并应用！')
    fetchSettings()
  } catch (error) {
    ElMessage.error('保存设置失败！')
    console.error(error)
  } finally {
    isSaving.value = false
  }
}
</script>

<style scoped>
.settings-container {
  height: 100vh; /* 使布局占满整个视口高度 */
}

.settings-aside {
  border-right: 1px solid var(--el-border-color);
}

.settings-menu {
  height: 100%;
  border-right: none; /* 移除菜单自身的右边框 */
}

/* 为 el-main 添加一个 class 以便更好地控制样式 */
.settings-main {
  padding: 0; /* 移除 el-main 的内边距，交由子元素控制 */
  position: relative; /* 为 sticky 定位提供上下文 */
}

.top-actions {
  position: sticky;
  top: 0;
  z-index: 10; /* 确保在最上层 */
  background-color: #ffffff; /* 添加背景色以防内容透出 */
  padding: 16px 24px;
  border-bottom: 1px solid var(--el-border-color);
  display: flex;
  justify-content: flex-start; /* 将按钮靠右对齐 */
  gap: 16px;
}

.settings-view {
  padding: 24px;
}

.downloader-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
  gap: 24px;
}

.downloader-card {
  display: flex;
  flex-direction: column;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-controls {
  display: flex;
  align-items: center;
}

.el-form {
  padding-top: 10px;
}

/* 原始的 .save-footer 样式已不再需要，可以删除 */
</style>
